"""Mini App 2.0 — read-only термінал сценаріїв Лева.

Не GGShot. Без ордерів, без auto-trading, без вигаданих WR/PnL.
PNG лишається для Telegram; у Mini App — інтерактивний графік.
"""
from __future__ import annotations

import re

import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from office_bridge import _fetchall, is_confirmed_position_row, signal_get_active
from office_confluence import lifecycle_from_status, scenario_story
from office_desk_card import is_legacy_desk_range, MAJORS, MAJORS_TP1_PCT, ALTS_TP1_PCT, MIN_SL_ATR_H1
from office_mini_v1 import (
    DATA_UNAVAILABLE,
    _complete_levels,
    _db,
    _f,
    home_payload as v1_home,
    scanner_payload as v1_scanner,
    stats_payload as v1_stats,
)
from office_price_format import format_level_span, format_price_fields, format_px, tick_size_for
from office_radar import MIN_RR
from office_signal_stats import MIN_GROUP, build_stats_report

TF_MAP = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}
WEB = Path(__file__).resolve().parent / "office_web" / "mini_v2.html"


def _git_sha() -> str:
    return (os.getenv("RENDER_GIT_COMMIT") or os.getenv("SOURCE_VERSION") or "")[:40]


def _fixture_on() -> bool:
    return os.getenv("OFFICE_MINI_FIXTURE", "").strip() in ("1", "true", "YES")


def parse_note(note: Any) -> Dict[str, Any]:
    raw = str(note or "")
    out: Dict[str, Any] = {"raw": raw[:500], "ckey": "", "grade": "", "tags": []}
    for part in raw.replace(",", " ").split():
        if part.startswith("ckey="):
            out["ckey"] = part[5:]
        if part.startswith("grade="):
            out["grade"] = part[6:].upper()
        if part.upper() in ("A", "B") and len(part) == 1:
            out["grade"] = part.upper()
    low = raw.lower()
    if "ckey=" in low and not out["ckey"]:
        try:
            out["ckey"] = raw.split("ckey=", 1)[1].split()[0]
        except Exception:
            pass
    return out


def potential_tp1(*, entry: Any, tp1: Any, sl: Any, symbol: str = "") -> Dict[str, Any]:
    e, t, s = _f(entry), _f(tp1), _f(sl)
    if e is None or t is None or e <= 0:
        return {"pct": None, "rr": None, "ok_filter": False, "reason": "немає TP1"}
    pct = abs(t - e) / e * 100.0
    rr = None
    if s is not None and abs(e - s) > 1e-12:
        rr = abs(t - e) / abs(e - s)
    maj = str(symbol or "").upper() in MAJORS
    need = MAJORS_TP1_PCT if maj else ALTS_TP1_PCT
    ok = pct + 1e-9 >= need and (rr is None or rr + 1e-9 >= float(MIN_RR))
    return {"pct": round(pct, 3), "rr": None if rr is None else round(rr, 2), "ok_filter": ok, "min_pct": need}


def lifecycle_for_row(row: Dict[str, Any], *, has_position: bool = False) -> Dict[str, str]:
    note = parse_note(row.get("analysis_note") or row.get("note"))
    confirms = []
    blob = note.get("raw") or ""
    if "confirm" in blob.lower() or "sfp" in blob.lower() or "engulf" in blob.lower():
        confirms = ["ltf"]
    return lifecycle_from_status(
        row.get("status"),
        confirms=confirms,
        has_position=has_position,
        ttl_done=str(row.get("status") or "").upper() == "EXPIRED",
    )


def _signal_rows(limit: int = 80, *, all_status: bool = False) -> List[Dict[str, Any]]:
    try:
        if all_status:
            rows = _fetchall(
                _db(),
                """
                SELECT signal_id, symbol, direction, entry_low, entry_high, sl, tp1, tp2, rr,
                       status, ts_created, ts_updated, outcome, analysis_note
                FROM office_signals
                ORDER BY ts_created DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            rows = signal_get_active(_db())
            return [r for r in (rows or []) if isinstance(r, dict)]
    except Exception:
        return []
    out = []
    for r in rows or []:
        out.append(
            {
                "signal_id": r[0],
                "symbol": r[1],
                "direction": r[2],
                "entry_low": r[3],
                "entry_high": r[4],
                "sl": r[5],
                "tp1": r[6],
                "tp2": r[7],
                "rr": r[8],
                "status": r[9],
                "ts_created": r[10],
                "ts_updated": r[11],
                "outcome": r[12],
                "analysis_note": r[13],
            }
        )
    return out


STATUS_UA = {
    "WATCHING": ("👁", "WATCHING", "Спостереження · входу немає"),
    "ACTIVE": ("🎯", "ПЛАН", "План активний · очікує рішення трейдера"),
    "CONFIRMED": ("✅", "ПІДТВЕРДЖЕНО", "Умову підтверджено · не позиція"),
    "HIT_ENTRY": ("📍", "ЗОНА ВХОДУ", "Ціна в зоні входу · не позиція"),
    "HIT_TP1": ("🏁", "TP1 (модель)", "Модельний TP1 · не PnL угоди"),
    "HIT_TP2": ("🏁", "TP2 (модель)", "Модельний TP2 · не PnL угоди"),
    "HIT_SL": ("⛔", "SL (модель)", "Модельний SL · не збиток угоди"),
    "CANCELLED": ("✖", "СКАСОВАНО", "Сценарій скасовано до входу"),
    "EXPIRED": ("⌛", "ПРОСТРОЧЕНО", "Термін сценарію минув"),
    "INVALIDATED": ("✖", "ІНВАЛІДОВАНО", "Теза зламалась до входу"),
    "PIERCE_WATCHING": ("👁", "WATCHING", "Спостереження після проколу рівня · входу немає"),
    "RANGE_WATCHING": ("👁", "WATCHING", "Спостереження за діапазоном · входу немає"),
}
_DONE = ("HIT_TP1", "HIT_TP2", "HIT_SL", "CANCELLED", "EXPIRED", "INVALIDATED", "CLOSED")
_LIVE = ("ACTIVE", "CONFIRMED", "HIT_ENTRY")


def status_view(status: Any) -> Dict[str, str]:
    """Статус завжди текстом і значком, не лише кольором."""
    st = str(status or "").upper()
    icon, short, long_ = STATUS_UA.get(st, ("•", st or "—", st or "Невідомий стан"))
    if st.endswith("WATCHING"):
        group = "watch"
    elif st in _LIVE:
        group = "live"
    elif st in _DONE:
        group = "done"
    else:
        group = "unknown"  # невідомий стан не ховаємо в архів і не видаємо за план
    return {"code": st, "icon": icon, "short": short, "text": long_, "group": group}


def _ttl_status(row: Dict[str, Any]) -> Dict[str, Any]:
    """WATCHING понад TTL показуємо чесно; саму БД не змінюємо (це робить worker за прапорцем)."""
    from office_lifecycle import WATCHING_EXPIRE_SEC, watching_ttl_exceeded

    v = dict(status_view(row.get("status")))
    if watching_ttl_exceeded(row.get("status"), row.get("ts_created"), datetime.now(timezone.utc)):
        v["ttl_exceeded"] = True
        v["text"] = f"{v['text']} · понад TTL {WATCHING_EXPIRE_SEC // 3600} год — теза могла застаріти"
    return v


def note_lines(note: Any) -> Dict[str, Optional[str]]:
    """Рядки «Чекаю / Що скасує / Чому» з фактичного тексту картки Лева. Не генеруємо."""
    wait = cancel = why = None
    for raw in str(note or "").splitlines():
        line = raw.strip()
        low = line.lower()
        if not line:
            continue
        if wait is None and low.startswith("чекаю"):
            wait = line[:300]
        elif cancel is None and low.startswith("що скасує"):
            cancel = line.split(":", 1)[-1].strip()[:300] or None
        elif why is None and low.startswith("чому"):
            why = line.split(":", 1)[-1].strip()[:400] or None
    return {"wait": wait, "cancel": cancel, "why": why}


def rr_text(rr: Any) -> Optional[str]:
    x = _f(rr)
    return None if x is None else f"1:{x:.1f}"


def scenario_card(row: Dict[str, Any], *, has_position: bool = False) -> Dict[str, Any]:
    note = parse_note(row.get("analysis_note"))
    lo, hi = _f(row.get("entry_low")), _f(row.get("entry_high"))
    mid = None
    if lo is not None and hi is not None:
        mid = (lo + hi) / 2.0
    elif lo is not None:
        mid = lo
    pot = potential_tp1(entry=mid, tp1=row.get("tp1"), sl=row.get("sl"), symbol=str(row.get("symbol") or ""))
    labs = []
    raw = str(note.get("raw") or "")
    from office_confluence import TAG_UA

    for tag, ua in TAG_UA.items():
        if tag in raw.lower() or ua.lower() in raw.lower():
            labs.append(ua)
    if "ob" in raw.lower() and "OB" not in labs:
        labs.append("OB")
    story = scenario_story(
        timeframe="H1",
        zone_lo=lo,
        zone_hi=hi,
        tags=[],
        labels=labs,
        wait_tf="M15",
        confirms=[],
        direction=str(row.get("direction") or ""),
        symbol=str(row.get("symbol") or ""),
    )
    if not labs and note.get("grade"):
        story = {
            **story,
            "text": (
                (story.get("text") or "").replace("незалежних збігів немає", f"сила {note.get('grade')} (теги в нотатці не розкладені)")
            ),
        }
    life = lifecycle_for_row(row, has_position=has_position)
    sym = str(row.get("symbol") or "")
    side = str(row.get("direction") or "").upper()
    rr_val = pot.get("rr") if pot.get("rr") is not None else _f(row.get("rr"))
    lines = note_lines(row.get("analysis_note"))
    display = {
        "zone": format_level_span(lo, hi, sym) if lo is not None else "",
        "entry": format_px(mid, sym),
        "sl": format_px(row.get("sl"), sym, side=side, kind="SL"),
        "tp1": format_px(row.get("tp1"), sym, side=side, kind="TP1"),
        "tp2": format_px(row.get("tp2"), sym, side=side, kind="TP2"),
        "rr": rr_text(rr_val),
        "rr_basis": "від середини зони входу до TP1" if rr_val is not None else None,
        "potential": None if pot.get("pct") is None else f"{pot['pct']:.1f}%",
        "tick": format(tick_size_for(sym, mid if mid is not None else row.get("sl")), "f"),
    }
    from office_scenario_state import list_label

    return {
        "scenario_id": row.get("signal_id"),
        "human": list_label(row),
        "symbol": row.get("symbol"),
        "direction": row.get("direction"),
        "status_raw": row.get("status"),
        "lifecycle": life,
        "grade": note.get("grade") or "",
        "timeframe": "H1",
        "zone_lo": lo,
        "zone_hi": hi,
        "entry": mid,
        "sl": _f(row.get("sl")),
        "tp1": _f(row.get("tp1")),
        "tp2": _f(row.get("tp2")),
        "rr": rr_val,
        "display": display,
        "status": _ttl_status(row),
        "wait": lines["wait"],
        "cancel": lines["cancel"],
        "why": lines["why"],
        "potential_pct": pot.get("pct"),
        "tp1_filter_ok": pot.get("ok_filter"),
        "as_of": row.get("ts_updated") or row.get("ts_created"),
        "created_at": row.get("ts_created"),
        "story": story,
        "opens_position": False,
        "kind": "lev_scenario",
        "legacy_range": is_legacy_desk_range(row),
    }


def list_scenarios(*, include_watching: bool = False) -> List[Dict[str, Any]]:
    from office_alert_gate import get_explicit_open_position

    rows = _signal_rows(80, all_status=True)
    out = []
    seen = set()
    pos_cache: Dict[str, bool] = {}
    for r in rows:
        if is_legacy_desk_range(r):
            continue
        st = str(r.get("status") or "").upper()
        if st == "WATCHING" and not include_watching:
            continue
        if st in ("ACTIVE", "HIT_ENTRY", "HIT_TP1", "CONFIRMED") or include_watching:
            if not _complete_levels(r) and st != "WATCHING":
                continue
        elif st in ("EXPIRED", "CANCELLED", "HIT_SL", "HIT_TP2"):
            pass
        else:
            if not _complete_levels(r):
                continue
        key = f"{r.get('symbol')}|{r.get('direction')}|{r.get('signal_id')}"
        if key in seen:
            continue
        seen.add(key)
        ck = f"{str(r.get('symbol') or '').upper()}|{str(r.get('direction') or '').upper()}"
        if ck not in pos_cache:
            pos_cache[ck] = bool(
                get_explicit_open_position(_db(), r.get("symbol") or "", r.get("direction") or "").get("ok")
            )
        out.append(scenario_card(r, has_position=pos_cache[ck]))
    return out


def _btc_regime() -> Optional[str]:
    """Режим ринку лише з market_state Worker. Сесія не підставляється як режим."""
    try:
        from office_market_state import market_state_get

        st = market_state_get(_db(), "BTCUSDT") or {}
        reg = str(st.get("regime") or "").strip()
        return reg or None
    except Exception:
        return None


def home_v2() -> Dict[str, Any]:
    base = v1_home()
    cards = [c for c in list_scenarios(include_watching=False) if not c.get("legacy_range")]
    ready = [c for c in cards if str((c.get("lifecycle") or {}).get("key")) in ("found", "confirmed", "waiting_zone")]
    return {
        **{k: base.get(k) for k in ("ok", "readonly", "btc", "sessions", "git_sha", "db_backend", "as_of")},
        "worker": {
            "t7": None,
            "note": "стан Worker з /api/summary t7_status на Web; тут без секретів",
        },
        "market_mode": base.get("market_mode"),
        "market_regime": _btc_regime(),
        "gex": None,
        "gex_status": DATA_UNAVAILABLE,
        "gex_reason": "шар GEX не в main",
        "orders": False,
        "opens_position": False,
        "ready_count": len(ready),
        "scenarios": ready[:8],
        "card_note": "Сценарій Лева ≠ позиція. Угода лише через /position.",
        "fixture_mode": _fixture_on(),
        "live_verified": False if _fixture_on() else None,
        "atr_note": f"гейті заморожені: ATR 80/90 · Edge 85 · MIN_RR {MIN_RR} · стоп ≥{MIN_SL_ATR_H1}×ATR H1",
    }


def dedupe_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Один сценарій — один рядок. Службові `lev-watch-*` та `watch-*` рядки, що дублюють відправлену картку Лева (той самий
    символ і напрям, зона перетинається), ховаємо: правду про стан веде картка. Умови з діалогу (`W-…`) теж не дублюємо."""
    strong = [c for c in cards if str(c.get("scenario_id") or "").startswith("SCN|") or str(c.get("status_raw") or "").upper() in ("ACTIVE", "CONFIRMED", "HIT_ENTRY")
              and not str(c.get("scenario_id") or "").startswith(("lev-watch-", "watch-"))]
    out = []
    seen_radar = set()
    for c in cards:
        sid = str(c.get("scenario_id") or "")
        if sid.startswith(("lev-watch-", "watch-")) or sid.startswith("W-"):
            lo, hi = _f(c.get("zone_lo")), _f(c.get("zone_hi"))
            shadowed = False
            for st in strong:
                if st is c or st.get("symbol") != c.get("symbol") or str(st.get("direction")).upper() != str(c.get("direction")).upper():
                    continue
                slo, shi = _f(st.get("zone_lo")), _f(st.get("zone_hi"))
                if sid.startswith("watch-") or lo is None or hi is None or slo is None or shi is None:
                    shadowed = True   # радарний рядок / без власної зони: той самий символ і напрям уже покрито карткою
                elif min(hi, shi) - max(lo, slo) >= 0:
                    shadowed = True
                if shadowed:
                    break
            if shadowed:
                continue
            key = (c.get("symbol"), str(c.get("direction")).upper(), sid.split("-")[0])
            if key in seen_radar:      # радарні рядки near/sweep × scalp/intraday — один на монету й напрям
                continue
            seen_radar.add(key)
        out.append(c)
    return out


def scenarios_payload(*, watching: bool = False) -> Dict[str, Any]:
    cards = dedupe_cards(list_scenarios(include_watching=watching))
    live = [c for c in cards if str(c.get("status_raw") or "").upper() in ("ACTIVE", "HIT_ENTRY", "HIT_TP1", "CONFIRMED", "WATCHING")]
    return {
        "ok": True,
        "readonly": True,
        "data_status": "DATA_OK" if live else "EMPTY",
        "empty_reason": None if live else "немає придатних сценаріїв Лева",
        "scenarios": cards[:40],
    }


def scenario_detail(sid: str) -> Dict[str, Any]:
    sid = str(sid or "").strip()
    if not sid:
        return {"ok": False, "data_status": DATA_UNAVAILABLE, "missing": ["scenario_id"]}
    row = None
    watch_thesis = None
    if sid.startswith("W-"):
        row, watch_thesis = _watch_as_row(sid)   # умова, яку Лев зберіг у діалозі: та сама сторінка й той самий стан
    for r in ([] if row is not None else _signal_rows(200, all_status=True)):
        if str(r.get("signal_id")) == sid:
            row = r
            break
    if row is None or is_legacy_desk_range(row):
        return {"ok": False, "data_status": DATA_UNAVAILABLE, "missing": ["сценарій"]}
    pos = False
    try:
        from office_alert_gate import get_explicit_open_position

        rec = get_explicit_open_position(
            _db(), str(row.get("symbol") or ""), str(row.get("direction") or "")
        )
        pos = bool(rec.get("ok"))
        pos_known: Optional[bool] = pos
    except Exception:
        pos = False
        pos_known = None
    card = scenario_card(row, has_position=pos)
    execution = None
    if (card.get("status") or {}).get("group") != "done":
        execution = execution_payload(card, has_open_position=pos_known)
    events = scenario_events(sid)
    thesis = watch_thesis
    if thesis is None:
        try:
            from office_thesis_journal import latest_thesis

            thesis = latest_thesis(_db(), sid)
        except Exception:
            thesis = None
    human = None
    try:
        human = _human_view(row, thesis, events)
    except Exception as exc:  # noqa: BLE001
        print(f"[mini] human view failed {sid}: {type(exc).__name__}: {exc}")
    return {
        "ok": True,
        "readonly": True,
        "data_status": "DATA_OK",
        "scenario": card,
        "human": human,
        "events": events,
        "thesis": thesis,
        "execution": execution,
        "has_position": pos,
        "hypothetical": not pos,
    }


def _watch_as_row(sid: str):
    """Умову з LEV_WATCH подаємо як рядок сценарію (щоб Mini App і Telegram показували той самий стан)."""
    import office_lev_watch as W

    w = W._latest(_db()).get(sid)
    if not w:
        return None, None
    plan = w.get("plan") or {}
    state = str(w.get("state") or "WAIT")
    status = {"CONFIRMED": "CONFIRMED", "CANCELLED": "CANCELLED", "EXPIRED": "EXPIRED", "REJECTED": "CANCELLED", "HANDOFF": "ACTIVE"}.get(state, "ACTIVE")
    note = f"cancel={w.get('invalidation')}"
    if state == "CONFIRMED" and plan.get("entry") is not None:
        note += f" confirm_sent=1 confirmed_px={plan['entry']}"
    row = {"signal_id": sid, "symbol": w["symbol"], "direction": w["direction"], "entry_low": w["zone_lo"], "entry_high": w["zone_hi"],
           "sl": plan.get("sl"), "tp1": plan.get("tp1"), "tp2": plan.get("tp2"), "rr": None, "status": status,
           "ts_created": w.get("created_at"), "ts_updated": w.get("created_at"), "analysis_note": note}
    thesis = {"invalidation": f"закриття за {w.get('invalidation')}", "confirmation": f"Чекаю на {w.get('wait_tf') or 'M15'}: розворот у зоні"}
    return row, thesis


def _human_view(row: Dict[str, Any], thesis: Optional[Dict[str, Any]], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Людський стан сценарію (єдина логіка зі Telegram): свіжа ціна + цілі за рівнями + суворі умови готовності."""
    from office_lev_watch import check_plan
    from office_scenario_state import build
    from office_targets import levels, structural_targets
    from office_market_data import fetch_candles

    sym = str(row.get("symbol") or "").upper()
    price = _live_price(sym)
    targets = None
    lo, hi, tp1 = _f(row.get("entry_low")), _f(row.get("entry_high")), _f(row.get("tp1"))
    if not _fixture_on() and tp1 is not None and lo is not None and hi is not None:
        try:
            lv = levels(m15=fetch_candles(sym, "15m", 96), daily=fetch_candles(sym, "1d", 5), weekly=fetch_candles(sym, "1w", 4))
            targets = structural_targets(direction=str(row.get("direction") or ""), entry=(lo + hi) / 2.0, tp1=tp1, lv=lv)
        except Exception:  # noqa: BLE001
            targets = None
    v = build(row, thesis=thesis, price=price, targets=targets, events=events, plan_check=check_plan)
    if v.get("state") == "READY":
        try:  # цілі 2/3 від фактичного входу, а не від середини зони
            entry = float(v_entry(row))
            lv2 = levels(m15=fetch_candles(sym, "15m", 96), daily=fetch_candles(sym, "1d", 5), weekly=fetch_candles(sym, "1w", 4))
            tg = structural_targets(direction=str(row.get("direction") or ""), entry=entry, tp1=tp1, lv=lv2)
            v = build(row, thesis=thesis, price=price, targets=tg, events=events, plan_check=check_plan)
        except Exception:  # noqa: BLE001
            pass
    return v


def v_entry(row: Dict[str, Any]) -> float:
    from office_scenario_state import _confirmed_px

    return float(_confirmed_px(row))


def execution_payload(card: Dict[str, Any], *, has_open_position: Optional[bool]) -> Dict[str, Any]:
    """Перевірки перед входом за поточною ціною (M1). Не ордер, рішень не змінює."""
    from office_execution_check import execution_checks

    sym = str(card.get("symbol") or "")
    pack = candles_payload(sym, "M1", 20)
    last = (pack.get("candles") or [None])[-1]
    fresh = pack.get("data_status") == "DATA_OK" and not pack.get("fixture")
    maj = sym.upper() in MAJORS
    res = execution_checks(
        symbol=sym,
        direction=str(card.get("direction") or ""),
        zone_lo=card.get("zone_lo"),
        zone_hi=card.get("zone_hi"),
        sl=card.get("sl"),
        tp1=card.get("tp1"),
        price=(last or {}).get("close"),
        price_fresh=fresh,
        has_open_position=has_open_position,
        min_rr=float(MIN_RR),
        min_tp1_pct=float(MAJORS_TP1_PCT if maj else ALTS_TP1_PCT),
    )
    res["price_display"] = format_px((last or {}).get("close"), sym) if last else ""
    res["price_source"] = "fixture" if pack.get("fixture") else pack.get("source")
    return res


def scenario_events(sid: str) -> List[Dict[str, Any]]:
    """Лише фактичні рядки office_events. Без реконструкції."""
    try:
        rows = _fetchall(
            _db(),
            """
            SELECT ts_utc, event_type, signal_id, payload_json
            FROM office_events
            WHERE signal_id = ?
            ORDER BY ts_utc ASC
            LIMIT 80
            """,
            (sid,),
        )
    except Exception:
        rows = []
    out = []
    for r in rows or []:
        out.append(
            {
                "ts": r[0],
                "type": r[1],
                "scenario_id": r[2],
                "source": "office_events",
            }
        )
    return out


def synth_candles(symbol: str, tf: str, limit: int = 120) -> List[Dict[str, Any]]:
    """Явно позначений fixture — не Live Binance."""
    n = max(30, min(int(limit or 120), 300))
    interval = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(tf, 900)
    now = int(time.time())
    now = now - (now % interval)
    base = 100.0
    su = str(symbol or "BTCUSDT").upper()
    if "BTC" in su:
        base = 84000.0
    elif "ETH" in su:
        base = 3900.0
    elif "SOL" in su:
        base = 141.0
    elif "XAU" in su or "PAXG" in su:
        base = 2650.0
    out = []
    px = base
    seed = sum(ord(c) for c in su)
    for i in range(n):
        ts = now - (n - 1 - i) * interval
        drift = math.sin((i + seed) / 9.0) * base * 0.004
        o = px
        h = o + abs(drift) + base * 0.001
        l = o - abs(drift) * 0.6 - base * 0.0008
        cl = o + drift * 0.15
        # Остання свічка «дихає» — для демо оновлення, не Live-ринок.
        if i == n - 1:
            wobble = math.sin(time.time() / 6.0) * base * 0.0004
            cl = cl + wobble
            h = max(h, cl)
            l = min(l, cl)
        px = cl
        out.append(
            {
                "time": ts,
                "open": round(o, 6),
                "high": round(h, 6),
                "low": round(l, 6),
                "close": round(cl, 6),
                "volume": 10.0 + (i % 7),
                "ts": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "forming": i == n - 1,
                "fixture": True,
            }
        )
    return out


def candles_payload(symbol: str, tf: str, limit: int = 180) -> Dict[str, Any]:
    interval = TF_MAP.get(str(tf or "H1").upper(), TF_MAP.get(str(tf or "15m"), "15m"))
    lim = max(20, min(int(limit or 180), 500))
    live_stream = False
    bars: List[Dict[str, Any]] = []
    source = "fixture" if _fixture_on() else "binance_futures"
    if _fixture_on():
        bars = synth_candles(symbol, interval, lim)
        status = "DATA_OK"
        quote_mode = "polling_fixture"
    else:
        from office_market_data import fetch_candles

        raw = fetch_candles(symbol, interval, lim)
        if isinstance(raw, list) and raw:
            for r in raw:
                ts = r.get("ts")
                unix = None
                try:
                    unix = int(datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp())
                except Exception:
                    unix = None
                bars.append(
                    {
                        "time": unix,
                        "open": r.get("open"),
                        "high": r.get("high"),
                        "low": r.get("low"),
                        "close": r.get("close"),
                        "volume": r.get("volume"),
                        "ts": ts,
                        "forming": False,
                        "fixture": False,
                    }
                )
            if bars:
                bars[-1]["forming"] = True
            status = "DATA_OK"
            quote_mode = "polling"
        else:
            status = DATA_UNAVAILABLE
            quote_mode = "unavailable"
            source = "none"
    last = bars[-1] if bars else None
    feed = _feed_health(last.get("ts") if last else None, interval, source)
    if status == "DATA_OK" and not feed["usable_for_review"] and not _fixture_on():
        status = "STALE"
    return {
        "ok": bool(bars),
        "feed": feed,
        "readonly": True,
        "data_status": status,
        "live": False if _fixture_on() else live_stream,
        "is_live": False if _fixture_on() else live_stream,
        "quote_mode": quote_mode,
        "source": source,
        "fixture": bool(_fixture_on()),
        "symbol": str(symbol or "").upper(),
        "tf": interval,
        "as_of": last.get("ts") if last else None,
        "stale": status != "DATA_OK",
        "candles": bars,
    }


_INTERVAL_TF = {"1m": "M1", "5m": "M5", "15m": "M15", "1h": "H1", "4h": "H4", "1d": "D1"}


def _feed_health(open_ts: Any, interval: str, source: str) -> Dict[str, Any]:
    """Свіжість останньої свічки через office_feed_quality (не «є дані = актуально»)."""
    from office_feed_quality import assess_feed
    from office_thesis_journal import _observed_at

    now = datetime.now(timezone.utc)
    obs = _observed_at(str(open_ts) if open_ts else None, _INTERVAL_TF.get(interval, "M5"), now)
    res = assess_feed(
        {"kind": "ohlcv", "source": source if source not in ("none", "") else "", "observed_at": obs, "complete": bool(obs)},
        now_utc=now,
    )
    return {"quality": res["quality"], "usable_for_review": res["usable_for_review"],
            "age_seconds": res["age_seconds"], "reasons": res["reasons"]}


def _source_health() -> Dict[str, Any]:
    try:
        from office_market_data import source_health

        return source_health()
    except Exception:  # noqa: BLE001
        return {}


def overview_payload() -> Dict[str, Any]:
    from office_market_data import fetch_candles, fetch_top_movers

    marks = []
    for sym in ("BTCUSDT", "ETHUSDT", "XAUUSDT"):
        row = {"symbol": sym, "price": None, "as_of": None, "data_status": DATA_UNAVAILABLE, "source": "binance_futures"}
        raw = fetch_candles(sym, "1m", 2) if not _fixture_on() else synth_candles(sym, "1m", 2)
        if isinstance(raw, list) and raw:
            last = raw[-1]
            row["price"] = last.get("close")
            row["as_of"] = last.get("ts")
            row["data_status"] = "DATA_OK"
            if not _fixture_on() and not _feed_health(last.get("ts"), "1m", "binance_futures")["usable_for_review"]:
                row["data_status"] = "STALE"
            if _fixture_on():
                row["source"] = "fixture"
        marks.append(row)
    gainers = []
    losers = []
    if not _fixture_on():
        try:
            gainers = fetch_top_movers("gainers", 5) or []
            losers = fetch_top_movers("losers", 5) or []
        except Exception:
            gainers, losers = [], []
    return {
        "ok": True,
        "readonly": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source_health": _source_health(),
        "marks": marks,
        "gainers": gainers,
        "losers": losers,
        "oi": None,
        "funding": None,
        "gex": None,
        "unavailable": ["GEX", "OI", "funding"] if True else [],
        "forceOrder": "минулі ліквідації, не heatmap",
    }


AUDIT_TYPES = ("THESIS_VERSION", "RISK_SHADOW_REVIEW", "RISK_VETO")


def audit_payload(days: int = 7) -> Dict[str, Any]:
    """Аудит журналу рішень: лише лічильники фактичних записів, без WR/PnL."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = _fetchall(
            _db(),
            """
            SELECT event_type, payload_json FROM office_events
            WHERE ts_utc >= ? AND event_type IN ('THESIS_VERSION', 'RISK_SHADOW_REVIEW', 'RISK_VETO')
            ORDER BY id DESC LIMIT 5000
            """,
            (since,),
        )
    except Exception:
        return {"ok": False, "readonly": True, "data_status": DATA_UNAVAILABLE, "reason": "журнал недоступний"}
    counts = {t: 0 for t in AUDIT_TYPES}
    reasons: Dict[str, int] = {}
    would_veto = 0
    thesis_incomplete = 0
    regimes: Dict[str, int] = {}
    for et, pj in rows or []:
        counts[et] = counts.get(et, 0) + 1
        try:
            pl = json.loads(pj or "{}")
        except Exception:
            pl = {}
        if et in ("RISK_SHADOW_REVIEW", "RISK_VETO"):
            if pl.get("would_veto") or et == "RISK_VETO":
                would_veto += 1
            for r in pl.get("reasons") or []:
                reasons[str(r)] = reasons.get(str(r), 0) + 1
        elif et == "THESIS_VERSION":
            if not (pl.get("check") or {}).get("valid_for_analyst_review"):
                thesis_incomplete += 1
            reg = str(pl.get("regime") or "UNKNOWN")
            regimes[reg] = regimes.get(reg, 0) + 1
    reviews = counts["RISK_SHADOW_REVIEW"] + counts["RISK_VETO"]
    return {
        "ok": True,
        "readonly": True,
        "days": days,
        "data_status": "DATA_OK" if rows else "EMPTY",
        "counts": counts,
        "risk_reviews": reviews,
        "would_veto": would_veto,
        "top_veto_reasons": sorted(reasons.items(), key=lambda x: -x[1])[:6],
        "thesis_incomplete": thesis_incomplete,
        "regimes": sorted(regimes.items(), key=lambda x: -x[1]),
        "note": "Лічильники записів журналу, не результативність стратегії.",
    }


def journal_payload(*, kind: str = "scenarios") -> Dict[str, Any]:
    k = str(kind or "scenarios").lower()
    if k == "audit":
        return audit_payload()
    if k == "stats":
        st = v1_stats()
        n = int(st.get("n") or 0)
        if n < MIN_GROUP:
            return {
                **st,
                "curve": None,
                "wr_shown": False,
                "note": f"n={n} < {MIN_GROUP} — WR/криву не показуємо",
            }
        return {**st, "wr_shown": True}
    if k == "positions":
        return positions_v2()
    cards = list_scenarios(include_watching=True)
    return {
        "ok": True,
        "readonly": True,
        "kind": "scenarios",
        "data_status": "DATA_OK" if cards else "EMPTY",
        "rows": cards[:60],
    }


def positions_v2() -> Dict[str, Any]:
    try:
        rows = _fetchall(
            _db(),
            """
            SELECT trade_id, symbol, direction, status, entry_price, stop_loss, take_profit,
                   pnl_pct, entry_reason, setup_name, ts_open_utc
            FROM trade_journal
            ORDER BY ts_open_utc DESC
            LIMIT 80
            """,
            (),
        )
    except Exception:
        rows = []
    live = []
    for r in rows or []:
        if not is_confirmed_position_row(r[8], r[9], r[0]):
            continue
        live.append(
            format_price_fields(
                {
                    "trade_id": r[0],
                    "symbol": r[1],
                    "direction": r[2],
                    "status": r[3],
                    "entry": r[4],
                    "sl": r[5],
                    "tp": r[6],
                    "pnl_pct": r[7],
                    "source": "/position",
                    "as_of": r[10],
                },
                str(r[1] or ""),
            )
        )
    return {
        "ok": True,
        "readonly": True,
        "kind": "position_only",
        "data_status": "DATA_OK" if live else "EMPTY",
        "empty_reason": None if live else "Немає підтверджених позицій",
        "positions": live,
        "note": "Сигнали офісу сюди не потрапляють.",
    }


SCAN_STALE_SEC = 2 * 3600


def radar_reasons(c: Dict[str, Any]) -> List[str]:
    """«Чому в радарі» лише зі збережених полів market_state. Не сигнал."""
    out: List[str] = []
    for key, label in (("pump", "pump-score"), ("dump", "dump-score"), ("score", "score")):
        v = _f(c.get(key))
        if v is not None and not (key == "score" and (c.get("pump") is not None or c.get("dump") is not None)):
            out.append(f"{label} {v:g}")
    rsi = c.get("rsi")
    try:
        r = float(rsi)
        out.append(f"RSI {r:.0f}" + (" — перекупленість" if r >= 70 else (" — перепроданість" if r <= 30 else "")))
    except (TypeError, ValueError):
        pass
    if c.get("regime"):
        out.append(f"режим {c['regime']}")
    if c.get("decision"):
        out.append(f"рішення офісу: {c['decision']}")
    return out


def _age_sec(ts: Any) -> Optional[float]:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def scanner_v2() -> Dict[str, Any]:
    sc = v1_scanner()
    cands = []
    for c in sc.get("candidates") or []:
        age = _age_sec(c.get("as_of"))
        cands.append({
            **c,
            "reasons": radar_reasons(c),
            "stale": age is None or age > SCAN_STALE_SEC,
            "is_signal": False,
        })
    sc = {**sc, "candidates": cands}
    if cands:
        return {**sc, "empty_kind": None, "universe_note": "shortlist зі збереженого market_state Worker"}
    return {
        **sc,
        "data_status": "EMPTY",
        "empty_kind": "no_facts",
        "empty_reason": "немає збережених фактів скану (RSI/score) — не підставляємо BTC",
        "candidates": [],
    }


def channel_payload(symbol: str, tf: str) -> Dict[str, Any]:
    from office_regression_channel import regression_channel

    pack = candles_payload(symbol, tf, 140)
    ch = regression_channel(pack.get("candles") or [], length=min(100, len(pack.get("candles") or [])), deviation=2.0)
    return {**ch, "symbol": str(symbol or "").upper(), "tf": pack.get("tf")}


def settings_payload() -> Dict[str, Any]:
    return {
        "ok": True,
        "readonly": True,
        "language": "uk",
        "timezone": "Europe/Kyiv",
        "auto_trading": False,
        "orders": False,
        "notifications_wired": False,
        "risk_presets": {
            "available": False,
            "note": "Архітектура шаблонів ризику запланована. Без біржі, ключів і кнопок ENTER/CLOSE.",
        },
        "sources": {
            "postgres": str(_db()).lower().startswith("postgres"),
            "git_sha": _git_sha() or None,
            "gex": False,
            "oi": False,
        },
        "gates": {
            "atr_entry_block": 80,
            "atr_t0": 90,
            "edge": 85,
            "min_rr": MIN_RR,
            "tp1_majors_pct": MAJORS_TP1_PCT,
            "tp1_alts_pct": ALTS_TP1_PCT,
        },
    }


def session_payload(symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """План сесії з M15. Лише спостереження; ціни через tick-форматер."""
    from office_session_desk import session_brief

    import re

    sym = str(symbol or "BTCUSDT").upper()
    if not re.fullmatch(r"[A-Z0-9]{2,20}", sym):
        return {"ok": False, "readonly": True, "data_status": DATA_UNAVAILABLE, "reason": "некоректний символ",
                "order_authorized": False, "is_signal": False}
    if _fixture_on():
        raw = synth_candles(sym, "15m", 200)
    else:
        from office_market_data import fetch_candles

        raw = fetch_candles(sym, "15m", 200)
    brief = session_brief(raw if isinstance(raw, list) else [], symbol=sym)
    for k in ("previous", "current"):
        blk = brief.get(k)
        if isinstance(blk, dict):
            for f in ("high", "low", "close"):
                if blk.get(f) is not None:
                    blk[f + "_display"] = format_px(blk[f], sym)
    sp = brief.get("since_previous")
    if isinstance(sp, dict):
        for t in ("high_test", "low_test"):
            if isinstance(sp.get(t), dict) and sp[t].get("extreme") is not None:
                sp[t]["extreme_display"] = format_px(sp[t]["extreme"], sym)
    brief["fixture"] = bool(_fixture_on())
    brief["readonly"] = True
    brief["ok"] = brief.get("data_status") == "DATA_OK"
    return brief


def _exposure_block(confirmed: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ризик відкритих позицій із ручного обліку. «Нічого не внесено» ≠ «ризику немає»."""
    try:
        import office_positions as P

        if P.schema_present(_db()):
            ex = P.exposure(_db())
            if ex["status"] == "OK":
                return {"value": ex["risk_now_usdt"], "status": "OK", "unit": "USDT", "open": ex["n_open"],
                        "notional_usdt": ex.get("notional_usdt"),
                        "text": f"{ex['text']} Ризик до поточних стопів: {ex['risk_now_usdt']} USDT."}
            return {"value": None, "status": "NONE_RECORDED", "text": ex["text"]}
    except Exception:
        pass
    return {"value": None, "status": DATA_UNAVAILABLE,
            "text": "Дані про відкриті позиції не підтверджені (облік угод не активовано)."}


def risk_payload() -> Dict[str, Any]:
    """Екран «Ризик». Невідоме ≠ нуль: без перевіреного джерела — «Дані недоступні»."""
    pos = positions_v2()
    confirmed = pos.get("positions") or []
    vetoes: List[Dict[str, Any]] = []
    shadow: List[Dict[str, Any]] = []
    try:
        rows = _fetchall(
            _db(),
            """
            SELECT ts_utc, event_type, signal_id, payload_json
            FROM office_events
            WHERE event_type IN ('RISK_VETO', 'RISK_SHADOW_REVIEW')
            ORDER BY ts_utc DESC
            LIMIT 40
            """,
            (),
        )
        for r in rows or []:
            try:
                pl = json.loads(r[3] or "{}")
            except Exception:
                pl = {}
            item = {
                "ts": r[0],
                "type": r[1],
                "scenario_id": r[2],
                "symbol": pl.get("symbol"),
                "direction": pl.get("direction"),
                "would_veto": bool(pl.get("would_veto")),
                "reasons": [str(x) for x in (pl.get("reasons") or [])][:8],
            }
            (vetoes if r[1] == "RISK_VETO" else shadow).append(item)
    except Exception:
        vetoes, shadow = [], []
    plans = []
    for c in list_scenarios(include_watching=False):
        if c.get("legacy_range") or (c.get("status") or {}).get("group") != "live":
            continue
        plans.append(
            {
                "scenario_id": c.get("scenario_id"),
                "symbol": c.get("symbol"),
                "direction": c.get("direction"),
                "status": c.get("status"),
                "rr": (c.get("display") or {}).get("rr"),
                "risk_usdt": None,
                "risk_note": "Плановий ризик не розраховано: немає перевіреного капіталу",
            }
        )
    return {
        "ok": True,
        "readonly": True,
        "orders": False,
        "order_authorized": False,
        "equity": {"value": None, "status": DATA_UNAVAILABLE, "text": "Дані недоступні: капітал не підключено"},
        "exposure": _exposure_block(confirmed),
        "budget": {"value": None, "status": DATA_UNAVAILABLE, "text": "Ризиковий бюджет дня не затверджено"},
        "positions": confirmed,
        "plans": plans[:20],
        "vetoes": vetoes,
        "vetoes_note": None if vetoes else "Записів veto Risk Officer у журналі ще немає",
        "shadow": shadow[:20],
        "risk_mode": "enforce" if os.getenv("OFFICE_RISK_OFFICER_ENFORCE", "").strip() == "1" else "shadow",
        "limits": settings_payload().get("gates"),
        "note": "Схвалення аналітичного плану не створює ордер.",
    }


_DB_PROBE: Dict[str, Any] = {"ts": 0.0, "ok": True}
DB_FREE_PATHS = ("/api/v2/lev", "/api/v2/watches", "/api/v2/candles", "/api/v2/channel", "/api/v2/session", "/api/v2/settings")


def db_alive(*, ttl: float = 5.0) -> bool:
    """Одне легке SELECT 1 (кеш 5 с). Без нього збій БД виглядав би як «немає сценаріїв»."""
    now = time.time()
    if now - float(_DB_PROBE["ts"]) < ttl:
        return bool(_DB_PROBE["ok"])
    try:
        _fetchall(_db(), "SELECT 1", ())
        ok = True
    except Exception:
        ok = False
    _DB_PROBE.update(ts=now, ok=ok)
    return ok


_PRICE_CACHE: Dict[str, Any] = {}


def _live_price(symbol: str) -> Dict[str, Any]:
    """Остання ціна M1 і чи вона свіжа (feed quality). Fixture/недоступно → не свіжа. Кеш 10 с."""
    sym = str(symbol or "").upper()
    now = time.time()
    hit = _PRICE_CACHE.get(sym)
    if hit and now - hit["t"] < 10:
        return hit["v"]
    pack = candles_payload(sym, "M1", 3)
    last = (pack.get("candles") or [None])[-1]
    fresh = bool(last) and pack.get("data_status") == "DATA_OK" and not pack.get("fixture")
    v = {"price": _f(last.get("close")) if last else None, "fresh": fresh, "as_of": pack.get("as_of"),
         "data_status": pack.get("data_status")}
    _PRICE_CACHE[sym] = {"t": now, "v": v}
    return v


def _scenario_status(sid: Optional[str]) -> Optional[str]:
    if not sid:
        return None
    try:
        r = _fetchall(_db(), "SELECT status FROM office_signals WHERE signal_id = ?", (str(sid),))
        return str(r[0][0]) if r else None
    except Exception:
        return None


def _with_display(pos: Dict[str, Any]) -> Dict[str, Any]:
    sym, side = pos["symbol"], pos["direction"]
    pos["display"] = {
        "entry": format_px(pos["entry"], sym),
        "sl": format_px(pos.get("sl"), sym, side=side, kind="SL") if pos.get("sl") else "",
        "tp1": format_px(pos.get("tp1"), sym, side=side, kind="TP1") if pos.get("tp1") else "",
        "tp2": format_px(pos.get("tp2"), sym, side=side, kind="TP2") if pos.get("tp2") else "",
        "exit": format_px(pos.get("exit_price"), sym) if pos.get("exit_price") else "",
    }
    return pos


def trades_payload(state: str = "open") -> Dict[str, Any]:
    import office_positions as P

    if not P.schema_present(_db()):
        return {"ok": True, "readonly": True, "schema_missing": True, "positions": [],
                "note": "Облік угод ще не активовано (потрібна міграція бази).", "order_authorized": False}
    rows = P.list_positions(_db(), state if state in ("open", "closed", "all") else "open", 100)
    out = []
    for p in rows:
        _with_display(p)
        if p["status"] == "OPEN":
            px = _live_price(p["symbol"])
            p["tracking"] = P.tracking(p, price=px["price"], price_fresh=px["fresh"],
                                       scenario_status=_scenario_status(p.get("scenario_id")))
            p["tracking"]["price_display"] = format_px(px["price"], p["symbol"]) if px["price"] else ""
            p["tracking"]["price_as_of"] = px["as_of"]
        out.append(p)
    return {"ok": True, "readonly": True, "positions": out, "exposure": P.exposure(_db()),
            "stats": P.stats(_db()), "order_authorized": False, "orders": False,
            "note": "Це ваші фактичні угоди, внесені вручну. Офіс не торгує і не змінює ордери на біржі."}


def trade_detail(trade_id: str) -> Dict[str, Any]:
    import office_positions as P

    try:
        pos = _with_display(P.get_position(_db(), trade_id))
    except P.PositionError as e:
        return {"ok": False, "error": e.code, "message": e.message}
    if pos["status"] == "OPEN":
        px = _live_price(pos["symbol"])
        pos["tracking"] = P.tracking(pos, price=px["price"], price_fresh=px["fresh"],
                                     scenario_status=_scenario_status(pos.get("scenario_id")))
    return {"ok": True, "position": pos, "order_authorized": False}


TRADE_ACTIONS = ("open", "partial", "move_sl", "move_tp", "close", "void", "note")


def trade_action(action: str, body: Dict[str, Any]) -> tuple:
    """Виконує ручний запис. Повертає (HTTP-код, JSON). Ордерів не створює."""
    import office_positions as P

    if action not in TRADE_ACTIONS:
        return 404, {"ok": False, "error": "unknown_action"}
    idem = str(body.get("idem_key") or "")[:80]
    tid = str(body.get("trade_id") or "")
    try:
        if action == "open":
            pos = P.open_position(
                _db(), symbol=body.get("symbol"), direction=body.get("direction"), entry=body.get("entry"),
                qty=body.get("qty"), sl=body.get("sl"), tp1=body.get("tp1"), tp2=body.get("tp2"),
                fee_usdt=body.get("fee_usdt"), opened_at=body.get("opened_at"),
                scenario_id=str(body.get("scenario_id") or "")[:200], note=str(body.get("note") or ""), idem_key=idem)
        elif action == "partial":
            pos = P.partial_exit(_db(), tid, price=body.get("price"), qty=body.get("qty"),
                                 fee_usdt=body.get("fee_usdt"), note=str(body.get("note") or ""), idem_key=idem)
        elif action == "move_sl":
            pos = P.move_sl(_db(), tid, sl=body.get("sl"), note=str(body.get("note") or ""), idem_key=idem)
        elif action == "move_tp":
            pos = P.move_tp(_db(), tid, tp1=body.get("tp1"), tp2=body.get("tp2"), note=str(body.get("note") or ""),
                            idem_key=idem)
        elif action == "close":
            pos = P.close_position(_db(), tid, price=body.get("price"), fee_usdt=body.get("fee_usdt"),
                                   note=str(body.get("note") or ""), exit_reason=str(body.get("exit_reason") or ""),
                                   idem_key=idem)
        elif action == "void":
            pos = P.void_position(_db(), tid, reason=str(body.get("reason") or ""), idem_key=idem)
        else:
            pos = P.add_note(_db(), tid, note=str(body.get("note") or ""), idem_key=idem)
    except P.PositionError as e:
        code = 409 if e.code in ("duplicate", "not_open") else (503 if e.code == "schema_missing" else
                                                              (404 if e.code == "not_found" else 422))
        return code, {"ok": False, "error": e.code, "message": e.message}
    return 200, {"ok": True, "position": _with_display(pos), "order_authorized": False, "orders": False}


def html_v2() -> str:
    if WEB.is_file():
        return WEB.read_text(encoding="utf-8")
    return "<!doctype html><p>Mini App 2.0 файл відсутній</p>"


def lev_payload(question: str = "", symbol: str = "") -> Dict[str, Any]:
    """«Запитати Лева» у Mini App: той самий грунтований діалог, що й у Telegram. Лише читання, БД не пишеться."""
    import office_lev_dialog as D

    q = str(question or "")[:200]
    sym = str(symbol or "").strip().upper()[:20]
    if sym and not re.fullmatch(r"[A-Z0-9]{2,20}", sym):
        return {"ok": False, "readonly": True, "reason": "некоректний символ", "order_authorized": False}
    text = (q + " " + sym).strip() or "аналіз"
    if _fixture_on():
        return {"ok": True, "readonly": True, "fixture": True, "symbol": sym or "BTCUSDT", "verdict": "NO_TRADE",
                "intent": D.detect_intent(q), "data_stale": True, "data_age_min": None, "order_authorized": False,
                "text": "FIXTURE: діалог із Левом вимкнено в тестовому режимі — це не ринок."}
    try:
        return {**D.answer(_db(), text, symbol=sym or None), "readonly": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "readonly": True, "reason": f"{type(exc).__name__}", "order_authorized": False}


WATCH_STATE_UA = {"WAIT": "чекаємо", "IN_ZONE": "ціна в зоні, чекаємо підтвердження", "CONFIRMED": "умови підтверджено"}


def watches_payload() -> Dict[str, Any]:
    """Що Лев зараз відстежує і що вже повідомляв — людською мовою. Лише читання."""
    import office_lev_watch as W
    from office_user_messages import ticker, _px

    try:
        act = W.active_watches(_db())
        notes = W.recent_notes(_db(), limit=8)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "readonly": True, "reason": type(exc).__name__, "order_authorized": False}
    items = []
    for w in act:
        sym = w["symbol"]
        items.append({"symbol": sym, "ticker": ticker(sym), "state": w["state"], "state_ua": WATCH_STATE_UA.get(w["state"], w["state"]),
                      "action_ua": "купівля" if w["direction"] == "LONG" else "продаж",
                      "zone": f"{_px(w['zone_lo'], sym).replace(' $', '')}–{_px(w['zone_hi'], sym)}",
                      "invalidation": _px(w["invalidation"], sym), "until": w.get("expires_at"), "since": w.get("created_at")})
    return {"ok": True, "readonly": True, "notify_enabled": W.notify_enabled(), "watches": items,
            "recent": [{"ts": n.get("ts"), "ticker": ticker(str(n.get("symbol"))), "event": n.get("event"),
                        "headline": str(n.get("text") or "").split("\n", 1)[0], "sent": bool(n.get("sent"))} for n in notes],
            "order_authorized": False}
