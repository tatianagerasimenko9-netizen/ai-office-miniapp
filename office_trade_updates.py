"""Ведення угоди, яку власниця позначила відкритою (кнопка «Я відкрила угоду…»): короткі рядки з дією, кожна подія — один раз.
Лише для відкритих позицій із `trade_journal`. Не ордери й не «позиція закрита»: без підтвердження виконання пишемо «ціна досягла».
Дедуп — у БД (`MANUAL_TRADE_ALERT` за (угода, код)); відповідь на початковий сигнал — за `confirm_msg_id` з плану."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

EV = "MANUAL_TRADE_ALERT"


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _px(v: Any, sym: str) -> str:
    from office_user_messages import _px as px

    return px(v, sym)


def texts(pos: Dict[str, Any], price: float) -> List[Dict[str, str]]:
    """Що сталося за поточною ціною для відкритої позиції (без урахування вже надісланого). Порядок важливості: стоп → TP3 → TP2 → TP1."""
    from office_user_messages import ticker

    side = str(pos.get("direction") or "").upper()
    long_ = side != "SHORT"
    sym = str(pos.get("symbol") or "")
    t = ticker(sym)
    entry, sl, t1, t2, t3 = (_f(pos.get(k)) for k in ("entry", "sl", "tp1", "tp2", "tp3"))
    out: List[Dict[str, str]] = []

    def beyond(level: Optional[float], up: bool) -> bool:
        return level is not None and ((price >= level) if (up == long_) else (price <= level))

    if sl is not None and ((price <= sl) if long_ else (price >= sl)):
        out.append({"code": "STOP_PRICE", "text": f"🔴 {t} · ціна досягла стопа"})
        return out
    if t3 is not None and beyond(t3, True):
        out.append({"code": "TP3", "text": f"🎯 {t} · TP3 · закрий залишок"})
    if t2 is not None and beyond(t2, True):
        out.append({"code": "TP2", "text": f"🎯 {t} · TP2 · закрий ще 30%, стоп на TP1 {_px(t1, sym)}" if t1 is not None else f"🎯 {t} · TP2 · закрий ще частину"})
    if t1 is not None and beyond(t1, True):
        out.append({"code": "TP1", "text": f"🎯 {t} · TP1 · закрий 40%, стоп у беззбиток {_px(entry, sym)}"})
    return out


def sent_codes(db: str, trade_id: str) -> Dict[str, float]:
    """Коди подій, які вже надсилались для цієї угоди → час (епоха) першої відправки."""
    import json

    from office_bridge import _fetchall
    from office_signal_track import _ts

    out: Dict[str, float] = {}
    for ts_utc, pj in _fetchall(db, "SELECT ts_utc, payload_json FROM office_events WHERE event_type = ? AND signal_id = ? ORDER BY id", (EV, trade_id)) or []:
        try:
            code = json.loads(pj).get("code")
        except (TypeError, ValueError):
            continue
        if code and code not in out:
            out[code] = _ts(ts_utc) or 0.0
    return out


def sent_before(db: str, trade_id: str, code: str) -> bool:
    return code in sent_codes(db, trade_id)


def record(db: str, trade_id: str, code: str, message_id: Any = None) -> None:
    from office_bridge import log_event

    log_event(db, EV, {"trade_id": trade_id, "code": code, "message_id": message_id}, trade_id)


def pending(db: str, price_of: Callable[[str], Optional[float]], candles_of: Optional[Callable[[str, str, int], Any]] = None,
            now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Що ще не надіслано для кожної відкритої ручної позиції — одна порада на позицію за прохід. Є свічки → повне ведення
    (office_trade_manager: беззбиток/TP/runner/трейлінг/добір/перезахід); немає → лише рівні за ціною (TP/стоп)."""
    import time

    import office_positions as OP
    import office_trade_manager as TM

    now = time.time() if now_ts is None else now_ts
    out: List[Dict[str, Any]] = []
    for pos in OP.list_positions(db, "open", 100):
        sym = str(pos.get("symbol") or "")
        px = price_of(sym)
        if px is None:
            continue
        sent = sent_codes(db, str(pos["trade_id"]))
        evs: List[Dict[str, str]] = []
        h1 = candles_of(sym, "1h", 120) if candles_of else None
        if isinstance(h1, list) and h1:
            m15 = candles_of(sym, "15m", 96)
            h4 = candles_of(sym, "4h", 60)
            evs = TM.advise(pos, h1=h1, m15=m15, h4=h4, sent=set(sent), now_ts=now, price=float(px))
            if "STOP_PRICE" in sent and not evs:
                re_ = TM.reentry(pos, m15=m15, h4=h4, sent=set(sent), now_ts=now, stop_alert_ts=sent.get("STOP_PRICE"))
                if re_:
                    evs = [re_]
        else:
            evs = [e for e in texts(pos, float(px)) if e["code"] not in sent]
        order = {"STOP_PRICE": 0, "END_STRUCTURE": 1, "END_STRUCTURE_H4": 1, "BREAKEVEN": 2, "TP1": 3, "TP2": 4, "TP3": 5}
        for ev in sorted(evs, key=lambda e: order.get(e["code"].split(":")[0], 9)):
            if ev["code"] == "STOP_PRICE" and ("END_STRUCTURE" in sent or "END_STRUCTURE_H4" in sent):
                continue
            out.append({"trade": pos, "code": ev["code"], "text": ev["text"]})
            break
    return out
