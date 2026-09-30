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
        out.append({"code": "TP2", "text": f"🎯 {t} · TP2 · закрий ще частину, стоп на TP1 {_px(t1, sym)}" if t1 is not None else f"🎯 {t} · TP2 · закрий ще частину"})
    if t1 is not None and beyond(t1, True):
        out.append({"code": "TP1", "text": f"🎯 {t} · TP1 · закрий 50%, стоп у беззбиток {_px(entry, sym)}"})
    return out


def sent_before(db: str, trade_id: str, code: str) -> bool:
    from office_bridge import _fetchall

    rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ? AND signal_id = ?", (EV, trade_id))
    import json

    for (pj,) in rows or []:
        try:
            if json.loads(pj).get("code") == code:
                return True
        except (TypeError, ValueError):
            continue
    return False


def record(db: str, trade_id: str, code: str, message_id: Any = None) -> None:
    from office_bridge import log_event

    log_event(db, EV, {"trade_id": trade_id, "code": code, "message_id": message_id}, trade_id)


def pending(db: str, price_of: Callable[[str], Optional[float]]) -> List[Dict[str, Any]]:
    """Що ще не надіслано для кожної відкритої ручної позиції: найвища за важливістю нова подія (один рядок на позицію за прохід)."""
    import office_positions as OP

    out: List[Dict[str, Any]] = []
    for pos in OP.list_positions(db, "open", 100):
        px = price_of(str(pos.get("symbol") or ""))
        if px is None:
            continue
        evs = texts(pos, float(px))
        # від найвищого TP до нижчого: якщо TP2 уже за ціною, а TP1 не надсилали — шлемо TP1 спершу (порядок дій зберігаємо)
        order = {"STOP_PRICE": 0, "TP1": 1, "TP2": 2, "TP3": 3}
        for ev in sorted(evs, key=lambda e: order.get(e["code"], 9)):
            if not sent_before(db, str(pos["trade_id"]), ev["code"]):
                out.append({"trade": pos, "code": ev["code"], "text": ev["text"]})
                break
    return out
