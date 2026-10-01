"""Одноразова перевірка Mini App на ЖИВИХ даних production (результат — у БД, подія LAUNCH_DIAG, task=ui_check; без змінних середовища).

Бере актуальний сценарій (перевага BTC), збирає ті самі дані, що бачить Mini App: новини (українською), статуси джерел окремо, шари графіка
по кожному ТФ (канал, FVG, сильна свічка, PDH/PDL). Лише читання й запис події в журнал; Telegram і ордерів немає."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List

VERSION = "ui-check-2026-10-01"
TFS = ("M1", "M5", "M15", "H1", "H4", "D1")
_LAT = re.compile(r"[A-Za-z]")


def _done(db: str) -> bool:
    from office_bridge import _fetchall

    try:
        rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ? ORDER BY id DESC LIMIT 300", ("LAUNCH_DIAG",))
    except Exception:  # noqa: BLE001
        return False
    for r in rows or []:
        try:
            p = json.loads(r[0]) if isinstance(r[0], str) else dict(r[0])
        except (TypeError, ValueError):
            continue
        if p.get("version") == VERSION and p.get("task") == "ui_check_done":
            return True
    return False


def _strings(o: Any) -> List[str]:
    if isinstance(o, str):
        return [o]
    if isinstance(o, dict):
        return [x for v in o.values() for x in _strings(v)]
    if isinstance(o, (list, tuple)):
        return [x for v in o for x in _strings(v)]
    return []


def _pick(cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    live = [c for c in cards if str((c.get("status") or {}).get("group") or "") in ("live", "watch")]
    pool = live or cards
    btc = [c for c in pool if str(c.get("symbol") or "").upper() == "BTCUSDT"]
    return (btc or pool or [{}])[0]


def run_once(db: str, printer=print) -> bool:
    if _done(db):
        return False
    from office_bridge import log_event

    def put(task: str, payload: Dict[str, Any]) -> None:
        log_event(db, "LAUNCH_DIAG", {"version": VERSION, "task": task, "at": time.time(), **payload})

    try:
        import office_mini_v2 as m

        sc = _pick((m.scenarios_payload(watching=True) or {}).get("scenarios") or [])
        sid = str(sc.get("scenario_id") or "")
        if not sid:
            put("ui_check", {"error": "немає жодного сценарію для перевірки"})
        else:
            det = m.scenario_detail(sid)
            hm = det.get("human") or {}
            ctx = hm.get("context") or {}
            news = hm.get("news")
            lat = sorted(set(_LAT.findall(re.sub(r"BTC|ETH|SOL", "", " ".join(_strings(news))))))   # лише ТЕКСТИ для користувача, не ключі JSON
            lv = hm.get("levels") or {}
            put("ui_check", {"symbol": sc.get("symbol"), "direction": sc.get("direction"), "scenario_id": sid, "state": (hm.get("state_ua") or ""),
                             "news": news, "news_latin_letters": lat, "sources": ctx.get("sources"), "not_connected": ctx.get("not_connected")})
            sym = str(sc.get("symbol") or "BTCUSDT")
            for tf in TFS:
                cx = m.chart_context_payload(sym, tf, str(sc.get("direction") or ""), sc.get("zone_lo"), sc.get("zone_hi"),
                                             [lv.get("tp1"), lv.get("tp2"), lv.get("tp3")])
                ch = cx.get("channel") or {}
                put("ui_check_chart", {"symbol": sym, "tf": tf, "ok": cx.get("ok"), "channel": bool(ch), "channel_start": ch.get("start_time"), "channel_end": ch.get("end_time"),
                                       "slope": ch.get("slope"), "fvg": cx.get("fvg"), "strong_candle": cx.get("strong_candle"), "previous": cx.get("previous"),
                                       "keys": sorted(cx.keys())})
    except Exception as exc:  # noqa: BLE001
        put("ui_check", {"error": f"{type(exc).__name__}: {exc}"})
    put("ui_check_done", {})
    printer("[ui-check] записано в БД (LAUNCH_DIAG)")
    return True
