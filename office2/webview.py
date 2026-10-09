"""Mini App: Office2 LIVE BETA — повний decision trace. Для кожного READY: РИНОК НА МОМЕНТ СИГНАЛУ (заморожений знімок) / РИНОК ЗАРАЗ / ЩО ЗМІНИЛОСЯ.
Знімок моменту сигналу ніколи не переписується; «зараз» береться з живого шару office2_shadow_state."""
from __future__ import annotations

import json
import os
import time
from typing import Tuple, Any, Dict, List, Optional


def _rows(db: str, sql: str, args: tuple = ()) -> list:
    from office_bridge import _fetchall

    try:
        return _fetchall(db, sql, args)
    except Exception:  # noqa: BLE001
        return []


def _latest_state(db: str, symbol: str) -> Optional[Dict[str, Any]]:
    r = _rows(db, "SELECT ts_epoch, payload_json FROM office2_shadow_state WHERE symbol = ? ORDER BY ts_epoch DESC LIMIT 1", (symbol,))
    if not r:
        return None
    d = json.loads(r[0][1])
    d["ts_epoch"] = r[0][0]
    return d


def _milestones(db: str, sid: str) -> List[Dict[str, Any]]:
    out = []
    for (pj,) in _rows(db, "SELECT payload_json FROM office_events WHERE event_type = 'SCENARIO_MILESTONE' AND signal_id = ? ORDER BY id ASC", (sid,)):
        try:
            out.append(json.loads(pj))
        except ValueError:
            pass
    return out


def what_changed(snap: Dict[str, Any], now_state: Optional[Dict[str, Any]], miles: List[Dict[str, Any]]) -> Dict[str, Any]:
    th = snap.get("thesis") or {}
    entry, sl = th.get("entry"), th.get("sl")
    out: Dict[str, Any] = {"levels_reached": [m.get("level") for m in miles]}
    if not now_state or not entry or sl is None:
        out["note"] = "поточних даних немає"
        return out
    px = now_state.get("price")
    risk = abs(entry - sl)
    sgn = 1.0 if snap.get("direction") == "LONG" else -1.0
    if px is not None and risk > 0:
        out["price_now"] = px
        out["move_pct"] = (px / entry - 1.0) * 100.0 * sgn
        out["move_r"] = (px - entry) * sgn / risk
        out["sl_distance_r"] = (px - sl) * sgn / risk
    mkt0 = ((snap.get("market_at_signal") or {}).get("market")) or {}
    mkt1 = now_state.get("market") or {}
    for k in ("btc_ret_1h", "breadth_up_4h", "median_vol_regime", "btc_reg4"):
        a, b = mkt0.get(k), mkt1.get(k)
        out[k] = {"at_signal": a, "now": b, "delta": (b - a) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None}
    return out


STATUS_UA = {"DELIVERED": "Надіслано", "PENDING": "Очікує відправки", "SUPPRESSED": "Не надіслано"}
STATE_UA = {"WATCH": "Спостерігаю", "WAIT": "Чекаю підтвердження", "READY": "Готово", "NO_TRADE": "Не торгувати", "MISSED": "Запізно", "INVALIDATED": "Скасовано", "EXPIRED": "Строк вийшов"}


def _frozen_chart(db: str, sid: str) -> Optional[Dict[str, Any]]:
    """Заморожені свічки моменту сигналу (ті самі, що на картці в Telegram) із події SIGNAL_PLAN."""
    for (pj,) in _rows(db, "SELECT payload_json FROM office_events WHERE event_type = 'SIGNAL_PLAN' AND signal_id = ? ORDER BY id DESC LIMIT 1", (sid,)):
        try:
            ch = (json.loads(pj).get("gate") or {}).get("chart") or {}
        except ValueError:
            continue
        if ch.get("candles"):
            return {"tf": ch.get("tf"), "candles": ch["candles"][-72:], "sha256": ch.get("sha256"), "source": ch.get("source")}
    return None


def resolve_scenario_id(db: str, ident: str) -> str:
    """Стабільний зв'язок подія → сценарій на боці сервера (не в UI). Повертає scenario_id батьківського Office2-сценарію або "".
    Приймає сам scenario_id або ідентифікатор lifecycle-події (повідомлення, надіслані до виправлення, містять «<scenario_id>|<confirmed_ts>|<рівень>»):
    це той самий сценарій, якщо він є в БД і ідентифікатор події починається з його id + «|»."""
    ident = str(ident or "").strip()
    if not ident:
        return ""
    if _rows(db, "SELECT 1 FROM office2_live_signal WHERE scenario_id = ?", (ident,)):
        return ident
    pre = _rows(db, "SELECT scenario_id FROM office2_live_signal WHERE scenario_id LIKE ? ORDER BY created_ts DESC LIMIT 1", (ident.replace("%", "").replace("_", "") + "|%",))   # id сценарію без «|час» → його сигнал
    if pre:
        return pre[0][0]
    if "|" in ident:
        for (sid,) in _rows(db, "SELECT scenario_id FROM office2_live_signal ORDER BY LENGTH(scenario_id) DESC"):
            if ident.startswith(sid + "|"):
                return sid
    return ""


def _stats(db: str) -> Optional[Dict[str, Any]]:
    try:
        from office2 import stats as ST

        return ST.collect(db)
    except Exception:  # noqa: BLE001
        return None


RADAR_GROUPS = {0: "Готово (READY)", 1: "ARMED 3/3 — лишився тригер M15", 2: "WAIT 2/3 — чекаю ретрейс у зону", 3: "WAIT 1/3 — чекаю зсув структури", 4: "Інші, що формуються", 5: "Не торгувати", 6: "Запізно (MISSED)", 7: "Скасовано / строк вийшов"}


def radar_group(state: str, reason: Any) -> Tuple[int, str]:
    """Порядок Radar: що ближче до входу — вище. Етап береться з тексту причини Brain v2 (WAIT n/3)."""
    from office2.engine import stage_tag

    if state == "READY":
        g = 0
    elif state == "WAIT":
        g = {"WAIT 3/3": 1, "WAIT 2/3": 2, "WAIT 1/3": 3}.get(stage_tag(reason), 4)
    elif state == "WATCH":
        g = 4
    else:
        g = {"NO_TRADE": 5, "MISSED": 6}.get(state, 7)
    return g, RADAR_GROUPS[g]


def _funnel(db: str, t: float) -> Dict[str, Any]:
    """Воронка Brain: скільки (символ×напрям) на якому етапі за останній цикл і за 24 год, з причинами відсіву (NO_TRADE/MISSED/INVALIDATED)."""
    try:
        last = _rows(db, "SELECT MAX(ts) FROM office2_brain_funnel")
        ts = last[0][0] if last and last[0][0] else None
        if ts is None:
            return {"last": None, "day": []}
        now_rows = _rows(db, "SELECT stage, COUNT(*) FROM office2_brain_funnel WHERE ts = ? GROUP BY stage ORDER BY 2 DESC", (ts,))
        day = _rows(db, "SELECT stage, code, COUNT(*) FROM office2_brain_funnel WHERE ts > ? GROUP BY stage, code ORDER BY 3 DESC LIMIT 40", (int(t - 86400),))
        cyc = _rows(db, "SELECT COUNT(DISTINCT ts) FROM office2_brain_funnel WHERE ts > ?", (int(t - 86400),))
        return {"last": {"ts": ts, "stages": [{"stage": a, "n": b} for a, b in now_rows]}, "day": [{"stage": a, "code": b, "n": c} for a, b, c in day], "cycles_24h": cyc[0][0] if cyc else 0}
    except Exception:  # noqa: BLE001
        return {"last": None, "day": []}


def repair_legacy_texts(seq: Any, direction: str) -> Any:
    """Знімки до виправлення мали для SHORT неправильні підписи кроків (SL: «− люфт» замість «+ люфт»; ретрейс: «low … у зоні» замість «high … торкнувся зони»).
    Числа в знімку правильні й не змінюються; виправляється лише текст при показі (знімок у БД лишається незмінним)."""
    if direction != "SHORT" or not isinstance(seq, list):
        return seq
    out = []
    for x in seq:
        v = x.get("value") if isinstance(x, dict) else None
        if isinstance(v, str):
            if x.get("step") == "SL" and " − люфт" in v:
                v = v.replace(" − люфт", " + люфт", 1)
            elif x.get("step") == "ретрейс у зону" and v.startswith("low ") and " у зоні " in v:
                v = v.replace("low ", "high ", 1).replace(" у зоні ", " торкнувся зони ", 1)
            if v != x.get("value"):
                x = dict(x, value=v, repaired_text=True)
        out.append(x)
    return out


def signal_item(db: str, row: tuple, focus: bool) -> Dict[str, Any]:
    """Один сигнал Office2: легка форма для списків; для focus — ще заморожений знімок, рівні, «зараз», зміни, хід і графік моменту сигналу."""
    sid, sym, d, ct, vu, status, msg, sj = row
    snap = json.loads(sj or "{}")
    th = snap.get("thesis") or {}
    item: Dict[str, Any] = {"id": sid, "symbol": sym, "direction": d, "created_ts": ct, "valid_until_ts": vu, "status": status, "status_ua": STATUS_UA.get(status, status), "telegram_msg_id": msg,
                            "light": {"entry": th.get("entry"), "sl": th.get("sl")}}
    if focus:
        ns = _latest_state(db, sym)
        if not snap.get("alignment"):   # знімки до появи поля: узгодженість рахуємо з ЗАМОРОЖЕНИХ значень знімка (не з поточного ринку) і позначаємо це
            from office2 import align as AL

            ms = snap.get("market_at_signal") or {}
            snap["alignment"] = AL.alignment(d, ms.get("market") or {}, ms.get("relative") or {}, ((snap.get("context") or {}).get("htf")))
            snap["alignment_derived"] = True
        miles = _milestones(db, sid)
        item["frozen"] = {k: snap.get(k) for k in ("label", "evidence_status", "decided_utc", "why", "thesis", "market_at_signal", "trace", "context", "old_lev", "alignment", "alignment_derived", "sequence", "evidence", "evidence_counts", "version_id", "integral", "market_map", "smc")}
        item["frozen"]["sequence"] = repair_legacy_texts(item["frozen"]["sequence"], d)
        from office2 import levels as LVL

        item["levels"] = LVL.view_from_thesis(th)
        item["market_now"] = ({"ts_epoch": ns.get("ts_epoch"), "price": ns.get("price"), "market": ns.get("market"), "ret_1h": ns.get("ret_1h"), "rs_vs_btc_1h": ns.get("rs_vs_btc_1h")} if ns else None)
        item["changed"] = what_changed(snap, ns, miles)
        item["lifecycle"] = [{"level": m.get("level"), "touched_ts": m.get("touched_ts"), "sent_ts": m.get("sent_ts"), "price": m.get("price")} for m in miles]
        item["chart"] = _frozen_chart(db, sid)
    return item


def payload(db: str, now: Optional[float] = None, focus: str = "") -> Dict[str, Any]:
    t = time.time() if now is None else now
    states = {r[0]: r[1] for r in _rows(db, "SELECT state, COUNT(*) FROM office2_live_scenario GROUP BY state")}
    last = _rows(db, "SELECT MAX(ts_epoch), COUNT(DISTINCT symbol) FROM office2_shadow_state WHERE ts_epoch > ?", (int(t - 3600),))
    cols_s = "scenario_id, symbol, direction, kind, state, reason, updated_ts"
    live_rows = _rows(db, f"SELECT {cols_s} FROM office2_live_scenario WHERE state IN ('WATCH','WAIT','READY') ORDER BY updated_ts DESC LIMIT 150")
    done_rows = _rows(db, f"SELECT {cols_s} FROM office2_live_scenario WHERE state IN ('NO_TRADE','MISSED','INVALIDATED','EXPIRED') ORDER BY updated_ts DESC LIMIT 25")
    scen = []
    for r in list(live_rows) + list(done_rows):
        g, g_ua = radar_group(r[4], r[5])
        scen.append({"id": r[0], "symbol": r[1], "direction": r[2], "kind": r[3], "state": r[4], "state_ua": STATE_UA.get(r[4], r[4]), "reason": r[5], "updated_ts": r[6], "group": g, "group_ua": g_ua})
    scen.sort(key=lambda x: (x["group"], -float(x["updated_ts"] or 0)))
    cols = "scenario_id, symbol, direction, created_ts, valid_until_ts, status, msg_id, snapshot_json"
    rows = _rows(db, f"SELECT {cols} FROM office2_live_signal ORDER BY created_ts DESC LIMIT 20")
    requested = focus
    focus = resolve_scenario_id(db, focus) if focus else ""
    if focus and not any(r[0] == focus for r in rows):     # батьківський сценарій старший за останні 20 — беремо його за scenario_id напряму
        rows = _rows(db, f"SELECT {cols} FROM office2_live_signal WHERE scenario_id = ?", (focus,)) + rows
    if not focus and not requested and rows:
        focus = rows[0][0]    # без id відкриваємо найновіший сигнал, а не стрічку
    sigs = [signal_item(db, r, r[0] == focus) for r in rows]
    from office2 import brain as B

    sigs.sort(key=lambda x: 0 if x["id"] == focus else 1)
    cnt = {r[0]: r[1] for r in _rows(db, "SELECT 'state', COUNT(*) FROM office2_shadow_state UNION ALL SELECT 'event', COUNT(*) FROM office2_shadow_event UNION ALL SELECT 'outcome', COUNT(*) FROM office2_shadow_outcome")}
    return {"ok": True, "now": t, "label": "OFFICE2 · LIVE BETA", "evidence_status": B.EVIDENCE_STATUS,
            "flags": {"OFFICE2_SHADOW": os.getenv("OFFICE2_SHADOW", ""), "OFFICE2_LIVE": os.getenv("OFFICE2_LIVE", ""), "OFFICE2_LIVE_DELIVERY": os.getenv("OFFICE2_LIVE_DELIVERY", ""),
                      "OFFICE_OLD_READY_DELIVERY": os.getenv("OFFICE_OLD_READY_DELIVERY", "1")},
            "scenario_counts": states, "last_cycle_ts": last[0][0] if last and last[0][0] else None, "symbols_last_hour": last[0][1] if last else 0, "collected": cnt,
            "signals": sigs, "scenarios": scen, "funnel": _funnel(db, t), "modules": B.MODULES, "stats": _stats(db), "focus": focus, "requested": requested, "focus_found": bool(focus and any(x["id"] == focus for x in sigs))}


def parent_id(sid: Any) -> str:
    """id сигналу = id сценарію + «|час підтвердження»; id сценарію («O2|хеш») повертається без змін."""
    sid = str(sid)
    return sid.rsplit("|", 1)[0] if sid.count("|") >= 2 else sid


def _prices(db: str, t: float, symbols: List[str]) -> Dict[str, float]:
    """Остання відома ціна по монетах з шару офісу (не старіша за 3 год); одним запитом."""
    out: Dict[str, float] = {}
    want = set(symbols)
    for sym, pj in _rows(db, "SELECT symbol, payload_json FROM office2_shadow_state WHERE ts_epoch > ? ORDER BY ts_epoch DESC LIMIT 400", (int(t - 3 * 3600),)):
        if sym in want and sym not in out:
            try:
                px = json.loads(pj).get("price")
            except ValueError:
                continue
            if isinstance(px, (int, float)):
                out[sym] = float(px)
    return out


def radar(db: str, now: Optional[float] = None) -> Dict[str, Any]:
    """Єдиний Radar: усі сценарії Brain за етапами. Для кожного — монета, напрям, ціна зараз, потрібний рівень, наступна умова, термін дії."""
    t = time.time() if now is None else now
    cols = "scenario_id, symbol, direction, kind, state, reason, updated_ts, expires_ts, thesis_json, version"
    live = _rows(db, f"SELECT {cols} FROM office2_live_scenario WHERE state IN ('WATCH','WAIT','READY') ORDER BY updated_ts DESC LIMIT 150")
    done = _rows(db, f"SELECT {cols} FROM office2_live_scenario WHERE state IN ('NO_TRADE','MISSED','INVALIDATED','EXPIRED') ORDER BY updated_ts DESC LIMIT 25")
    rows = list(live) + list(done)
    px = _prices(db, t, [r[1] for r in rows])
    sigs = {parent_id(r[0]): (r[0], r[1]) for r in _rows(db, "SELECT scenario_id, valid_until_ts FROM office2_live_signal WHERE created_ts > ? ORDER BY created_ts ASC", (t - 3 * 86400,))}   # id сигналу = id сценарію + «|час»
    items = []
    for sid, sym, d, kind, state, reason, upd, exp, tj, ver in rows:
        try:
            th = json.loads(tj or "{}")
        except ValueError:
            th = {}
        g, g_ua = radar_group(state, reason)
        need = th.get("need") or {}
        now_px = px.get(sym)
        need_px = need.get("px")
        dist = ((need_px - now_px) / now_px * 100.0) if isinstance(need_px, (int, float)) and now_px else None
        items.append({"id": sid, "symbol": sym, "direction": d, "kind": kind, "state": state, "state_ua": STATE_UA.get(state, state), "group": g, "group_ua": g_ua, "reason": reason,
                      "price": now_px, "need_px": need_px, "need_text": need.get("text"), "dist_pct": dist, "invalidation": (th.get("invalidation") or {}).get("price"),
                      "zone": th.get("entry_zone"), "updated_ts": upd, "expires_ts": exp or (sigs.get(sid) or (None, None))[1], "signal_id": (sigs.get(sid) or (None, None))[0], "brain": ver or th.get("brain")})
    items.sort(key=lambda x: (x["group"], -float(x["updated_ts"] or 0)))
    groups: List[Dict[str, Any]] = []
    for it in items:
        if not groups or groups[-1]["group"] != it["group"]:
            groups.append({"group": it["group"], "title": it["group_ua"], "items": []})
        groups[-1]["items"].append(it)
    return {"ok": True, "now": t, "groups": groups, "n": len(items), "funnel": _funnel(db, t)}


def delivered(db: str, limit: int = 60) -> List[Dict[str, Any]]:
    """Надіслані READY Office2 у формі, зручній для списків основного Mini App: легкі поля + підсумок за віхами (вхід/TP/SL/строк)."""
    rows = _rows(db, "SELECT scenario_id, symbol, direction, created_ts, valid_until_ts, status, msg_id, snapshot_json FROM office2_live_signal WHERE status = 'DELIVERED' ORDER BY created_ts DESC LIMIT ?", (limit,))
    miles: Dict[str, List[str]] = {}
    ids = [r[0] for r in rows]
    if ids:
        q = "SELECT signal_id, payload_json FROM office_events WHERE event_type = 'SCENARIO_MILESTONE' AND signal_id IN (%s) ORDER BY id ASC" % ",".join("?" for _ in ids)
        for sid, pj in _rows(db, q, tuple(ids)):
            try:
                miles.setdefault(sid, []).append(json.loads(pj).get("level"))
            except ValueError:
                pass
    out = []
    for sid, sym, d, ct, vu, st, msg, sj in rows:
        snap = json.loads(sj or "{}")
        th = snap.get("thesis") or {}
        out.append({"id": sid, "symbol": sym, "direction": d, "created_ts": ct, "valid_until_ts": vu, "thesis": th, "levels": miles.get(sid, []), "version_id": snap.get("version_id"), "why": snap.get("why")})
    return out


def scenario(db: str, ident: str) -> Optional[Dict[str, Any]]:
    """Повний пакет одного сигналу Office2 для картки основного Mini App (за scenario_id або id lifecycle-події)."""
    sid = resolve_scenario_id(db, ident)
    if not sid:
        return None
    rows = _rows(db, "SELECT scenario_id, symbol, direction, created_ts, valid_until_ts, status, msg_id, snapshot_json FROM office2_live_signal WHERE scenario_id = ?", (sid,))
    return signal_item(db, rows[0], True) if rows else None
