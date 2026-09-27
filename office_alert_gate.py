"""Єдиний gate зовнішніх алертів: зона ≠ дозвіл на вхід.

Ключ origin: symbol|direction|zone|origin.
FOUND → WATCHING → ZONE_REACHED → CONFIRMATION_PENDING → CONFIRMED | INVALIDATED | EXPIRED.
Повторний ZONE_REACHED після CONFIRMED не дає новий ENTER.
Не змінює ATR 80/90, Edge 85, MIN_RR 1.5. Не ордер.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from office_telegram_filter import format_level_span, format_px

STATES = (
    "FOUND",
    "WATCHING",
    "ZONE_REACHED",
    "CONFIRMATION_PENDING",
    "CONFIRMED",
    "INVALIDATED",
    "EXPIRED",
)

INTENT_ZONE = "ZONE_IN"
INTENT_CONFIRM = "LTF_CONFIRM"
INTENT_ENTRY = "ENTRY_PERMISSION"
INTENT_HIT_ENTRY = "HIT_ENTRY_PRICE"
INTENT_POSITION = "POSITION_MANAGE"

_LIVE: Dict[str, Dict[str, Any]] = {}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def origin_key(
    *,
    symbol: str,
    direction: str,
    zone_lo: Any,
    zone_hi: Any,
    origin: str = "desk",
) -> str:
    lo, hi = _f(zone_lo), _f(zone_hi)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    a = f"{lo:.8f}" if lo is not None else ""
    b = f"{hi:.8f}" if hi is not None else a
    return (
        f"{str(symbol or '').upper()}|{str(direction or '').upper()}|{a}|{b}|"
        f"{str(origin or 'desk').strip().lower() or 'desk'}"
    )


def reset_alert_gate() -> None:
    _LIVE.clear()


def get_setup_state(key: str) -> Dict[str, Any]:
    st = _LIVE.get(str(key or ""))
    if not st:
        return {
            "state": "FOUND",
            "entry_alert_sent": False,
            "confirm_sent": False,
            "in_position": False,
        }
    return dict(st)


def apply_setup_event(
    key: str,
    event: str,
    *,
    in_zone: bool = False,
    ltf_ok: bool = False,
    invalidated: bool = False,
    expired: bool = False,
    in_position: bool = False,
) -> Dict[str, Any]:
    """Один крок машини. CONFIRMED — картка, не /position."""
    cur = get_setup_state(key)
    state = str(cur.get("state") or "FOUND").upper()
    ev = str(event or "").upper()
    if expired:
        state = "EXPIRED"
    elif invalidated:
        state = "INVALIDATED"
    elif state in ("CONFIRMED", "INVALIDATED", "EXPIRED"):
        if ev in ("ZONE_IN", "HIT_ENTRY", "ZONE_REACHED") and state == "CONFIRMED":
            state = "CONFIRMED"
        elif in_position:
            cur["in_position"] = True
    elif ev in ("FOUND",):
        state = "WATCHING"
    elif ev in ("ZONE_IN", "ZONE_REACHED"):
        if state in ("FOUND", "WATCHING"):
            state = "ZONE_REACHED"
        elif state == "ZONE_REACHED":
            state = "CONFIRMATION_PENDING"
        elif state == "CONFIRMATION_PENDING":
            state = "CONFIRMATION_PENDING"
    elif ev in ("WAIT_CONFIRM",):
        state = "CONFIRMATION_PENDING" if in_zone or state in ("ZONE_REACHED", "WATCHING") else state
    elif ev in ("LTF_CONFIRM", "CONFIRMED"):
        if ltf_ok:
            state = "CONFIRMED"
            cur["confirm_sent"] = True
    nxt = {
        **cur,
        "state": state,
        "in_position": bool(in_position or cur.get("in_position")),
        "key": key,
    }
    if key:
        _LIVE[key] = nxt
    return nxt


def may_emit_telegram(
    *,
    key: str = "",
    intent: str,
    state: str = "",
    ltf_confirmed: bool = False,
    quote_stale: bool = False,
    chase: bool = False,
    in_position: bool = False,
    in_zone: bool = False,
) -> Dict[str, Any]:
    """Жоден шлях не перетворює «ціна в зоні» на «можна входити»."""
    st = str(state or get_setup_state(key).get("state") or "").upper()
    rec = get_setup_state(key)
    intent_u = str(intent or "").upper()
    deny = {"send": False, "state": st, "opens_position": False}

    if quote_stale:
        return {**deny, "reason": "QUOTE_STALE"}
    if chase:
        return {**deny, "reason": "chase — старий entry не повторюємо"}

    if intent_u in (INTENT_ZONE, "ZONE_REACHED", INTENT_HIT_ENTRY, "HIT_ENTRY"):
        return {
            **deny,
            "reason": "ціна в зоні дозволяє лише очікування, не «можна входити»",
        }

    if intent_u in (INTENT_ENTRY, "SIGNAL_ENTRY", "MOZHNA"):
        if st == "CONFIRMED" or rec.get("entry_alert_sent") or rec.get("confirm_sent"):
            return {**deny, "reason": "після CONFIRMED новий дозвіл на вхід заборонено"}
        if not ltf_confirmed:
            return {**deny, "reason": "немає незалежного LTF-підтвердження"}
        if in_zone and not ltf_confirmed:
            return {**deny, "reason": "перебування в зоні ≠ вхід"}
        return {**deny, "reason": "ENTRY_PERMISSION лише через CONFIRMED-картку Лева, не T0"}

    if intent_u in (INTENT_CONFIRM, "CONFIRM"):
        if rec.get("confirm_sent") or st == "CONFIRMED":
            return {**deny, "reason": "підтвердження вже надіслано"}
        if not ltf_confirmed:
            return {**deny, "reason": "LTF не підтверджено"}
        return {
            "send": True,
            "reason": "одне LTF-підтвердження",
            "state": "CONFIRMED",
            "opens_position": False,
        }

    if intent_u in (INTENT_POSITION, "TP", "SL", "TRAIL"):
        if not in_position:
            return {**deny, "reason": "немає явного /position"}
        return {"send": True, "reason": "супровід зареєстрованої позиції", "state": st, "opens_position": False}

    return {**deny, "reason": f"невідомий intent {intent_u}"}


def mark_confirm_sent(key: str) -> None:
    if not key:
        return
    cur = get_setup_state(key)
    cur["confirm_sent"] = True
    cur["entry_alert_sent"] = True
    cur["state"] = "CONFIRMED"
    _LIVE[key] = cur


def format_zone_wait_message(
    *,
    symbol: str,
    current_price: Any,
    entry_low: Any,
    entry_high: Any,
    sl: Any = None,
    tp1: Any = None,
) -> str:
    """Текст очікування. Без «можна входити» і без float-сміття."""
    zone = format_level_span(entry_low, entry_high)
    px = format_px(current_price)
    lines = [
        f"{str(symbol or '').upper()} досяг зони {zone}.".replace("  ", " "),
        f"Зараз {px}. У зоні — чекаю підтвердження, не вхід.",
    ]
    if sl is not None:
        lines.append(f"SL {format_px(sl)}")
    if tp1 is not None:
        lines.append(f"TP1 {format_px(tp1)}")
    return "\n".join(lines)


def text_grants_entry(text: str) -> bool:
    low = str(text or "").lower()
    return "можна входити" in low or "входь" in low


def plan_metrics(
    *,
    entry: Any,
    sl: Any,
    tp1: Any,
) -> Dict[str, Any]:
    """SL%/TP1%/RR після витрат від фактичного entry."""
    from office_level_scalp import rr_after_costs

    e, s, t = _f(entry), _f(sl), _f(tp1)
    out: Dict[str, Any] = {
        "entry": e,
        "sl": s,
        "tp1": t,
        "sl_pct": None,
        "tp1_pct": None,
        "rr_net": None,
    }
    if e is None or e <= 0:
        return out
    if s is not None:
        out["sl_pct"] = abs(s - e) / e * 100.0
    if t is not None:
        out["tp1_pct"] = abs(t - e) / e * 100.0
    out["rr_net"] = rr_after_costs(entry=e, sl=s, tp=t)
    return out
