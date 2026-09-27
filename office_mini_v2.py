"""Mini App 2.0 — read-only термінал сценаріїв Лева.

Не GGShot. Без ордерів, без auto-trading, без вигаданих WR/PnL.
PNG лишається для Telegram; у Mini App — інтерактивний графік.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
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
from office_price_format import format_price_fields
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
    )
    if not labs and note.get("grade"):
        story = {
            **story,
            "text": (
                (story.get("text") or "").replace("немає незалежних збігів", f"сила {note.get('grade')} (теги в нотатці не розкладені)")
            ),
        }
    life = lifecycle_for_row(row, has_position=has_position)
    return {
        "scenario_id": row.get("signal_id"),
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
        "rr": pot.get("rr") if pot.get("rr") is not None else _f(row.get("rr")),
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
    rows = _signal_rows(80, all_status=True)
    out = []
    seen = set()
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
        out.append(scenario_card(r))
    return out


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


def scenarios_payload(*, watching: bool = False) -> Dict[str, Any]:
    cards = list_scenarios(include_watching=watching)
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
    for r in _signal_rows(200, all_status=True):
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
    except Exception:
        pos = False
    card = scenario_card(row, has_position=pos)
    events = scenario_events(sid)
    return {
        "ok": True,
        "readonly": True,
        "data_status": "DATA_OK",
        "scenario": card,
        "events": events,
        "has_position": pos,
        "hypothetical": not pos,
    }


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
    return {
        "ok": bool(bars),
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
        "marks": marks,
        "gainers": gainers,
        "losers": losers,
        "oi": None,
        "funding": None,
        "gex": None,
        "unavailable": ["GEX", "OI", "funding"] if True else [],
        "forceOrder": "минулі ліквідації, не heatmap",
    }


def journal_payload(*, kind: str = "scenarios") -> Dict[str, Any]:
    k = str(kind or "scenarios").lower()
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


def scanner_v2() -> Dict[str, Any]:
    sc = v1_scanner()
    cands = sc.get("candidates") or []
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


def html_v2() -> str:
    if WEB.is_file():
        return WEB.read_text(encoding="utf-8")
    return "<!doctype html><p>Mini App 2.0 файл відсутній</p>"
