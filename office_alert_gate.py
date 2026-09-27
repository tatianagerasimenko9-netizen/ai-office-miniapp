"""Єдиний gate зовнішніх алертів: зона ≠ дозвіл на вхід.

Ключ origin: symbol|direction|zone|origin.
FOUND → WATCHING → ZONE_REACHED → CONFIRMATION_PENDING → CONFIRMED | INVALIDATED | EXPIRED.
Повторний ZONE_REACHED після CONFIRMED не дає новий ENTER.
Не змінює ATR 80/90, Edge 85, MIN_RR 1.5. Не ордер.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from office_price_format import format_level_span, format_px
from office_radar import MIN_RR

STATES = (
    "FOUND",
    "WATCHING",
    "ZONE_REACHED",
    "CONFIRMATION_PENDING",
    "CONFIRMED",
    "CANCELLED",
    "INVALIDATED",
    "EXPIRED",
)

INTENT_ZONE = "ZONE_IN"
INTENT_CONFIRM = "LTF_CONFIRM"
INTENT_ENTRY = "ENTRY_PERMISSION"
INTENT_HIT_ENTRY = "HIT_ENTRY_PRICE"
INTENT_POSITION = "POSITION_MANAGE"
INTENT_ADD = "ADD_ON"

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
    timeframe: str = "",
) -> str:
    lo, hi = _f(zone_lo), _f(zone_hi)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    a = f"{lo:.8f}" if lo is not None else ""
    b = f"{hi:.8f}" if hi is not None else a
    base = (
        f"{str(symbol or '').upper()}|{str(direction or '').upper()}|{a}|{b}|"
        f"{str(origin or 'desk').strip().lower() or 'desk'}"
    )
    from office_scenario_memory import normalize_tf

    tf = normalize_tf(timeframe)
    return f"{base}|{tf}" if tf else base


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
    elif ev in ("CANCEL", "CANCELLED"):
        state = "CANCELLED"
    elif state in ("CONFIRMED", "CANCELLED", "INVALIDATED", "EXPIRED"):
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
        if st in ("CANCELLED", "INVALIDATED", "EXPIRED"):
            return {**deny, "reason": f"сценарій завершено: {st}"}
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

    if intent_u in (INTENT_ADD, "ADD", "ADD_ON", "SCALE_IN"):
        if not in_position:
            return {**deny, "reason": "немає явного /position — добір заборонено"}
        return {
            **deny,
            "reason": "добір не автоматичний: потрібна перевірка ризику і підтвердження Тетяни",
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


def hydrate_alert_gate_from_db(db_path: str) -> int:
    """Після рестарту: CONFIRMED у БД = confirm_sent, без другого CONFIRM."""
    from office_bridge import signal_get_active, signal_get_scenarios
    from office_desk_card import is_legacy_desk_range
    from office_scenario_memory import parse_note_meta

    n = 0
    try:
        canonical_rows = signal_get_scenarios(db_path) or []
        canonical_ids = {str(x.get("signal_id") or "") for x in canonical_rows}
        rows = canonical_rows + [
            x for x in (signal_get_active(db_path) or []) if str(x.get("signal_id") or "") not in canonical_ids
        ]
    except Exception:
        return 0
    for r in rows:
        if not isinstance(r, dict) or is_legacy_desk_range(r):
            continue
        st = str(r.get("status") or "").upper()
        note = str(r.get("analysis_note") or "")
        meta = parse_note_meta(note)
        key = str(meta.get("scenario_id") or meta.get("okey") or "").strip()
        if not key:
            key = origin_key(
                symbol=str(r.get("symbol") or ""),
                direction=str(r.get("direction") or ""),
                zone_lo=r.get("entry_low"),
                zone_hi=r.get("entry_high"),
                origin=str(meta.get("origin") or "desk"),
                timeframe=str(meta.get("timeframe") or ""),
            )
        if not key:
            continue
        confirmed = st in ("CONFIRMED", "HIT_ENTRY", "HIT_TP1", "HIT_TP2") or "confirm_sent=1" in note or "confirmed_px=" in note
        cancelled = st in ("CANCELLED", "STOPPED", "HIT_SL", "EXPIRED")
        prev = dict(_LIVE.get(key) or {})
        _LIVE[key] = {
            **prev,
            "state": "CANCELLED" if cancelled else ("CONFIRMED" if confirmed else str(prev.get("state") or "WATCHING")),
            "confirm_sent": bool(confirmed or prev.get("confirm_sent")),
            "entry_alert_sent": bool(confirmed or prev.get("entry_alert_sent")),
            "in_position": bool(prev.get("in_position")),
            "key": key,
        }
        n += 1
    return n


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
    sym = str(symbol or "")
    zone = format_level_span(entry_low, entry_high, sym)
    px = format_px(current_price, sym)
    lines = [
        f"{sym.upper()} досяг зони {zone}.".replace("  ", " "),
        f"Зараз {px}. У зоні — чекаю підтвердження, не вхід.",
    ]
    if sl is not None:
        lines.append(f"SL {format_px(sl, sym)}")
    if tp1 is not None:
        lines.append(f"TP1 {format_px(tp1, sym)}")
    return "\n".join(lines)


def text_grants_entry(text: str) -> bool:
    """Мова дозволу на ВХІД/добір. Не супровід уже відкритої /position."""
    low = str(text or "").lower()
    if "можна входити" in low or "входь" in low:
        return True
    if "добір позиції" in low or "добір дозволений" in low:
        return True
    if "збільшити позицію" in low:
        return True
    return False


def text_instructs_position_change(text: str) -> bool:
    """Наказ змінити ордер/розмір. Право дає лише verified /position, не ці слова."""
    low = str(text or "").lower()
    if "закрий 50" in low or "закрий ще" in low:
        return True
    if "готуйся закрити" in low or "фіксуй залишок" in low:
        return True
    if "перестав sl" in low or "перенести стоп позиції" in low:
        return True
    if "повний вихід з позиції" in low:
        return True
    if "sl в беззбиток" in low:
        return True
    if "позиція закрита" in low or "позицію закрито" in low:
        return True
    return False


def get_explicit_open_position(
    db_path: str, symbol: str, direction: str = ""
) -> Dict[str, Any]:
    """Відкрита /position з trade_id. Інакше fail-closed."""
    deny = {"ok": False, "open": False, "trade_id": "", "symbol": str(symbol or "").upper()}
    if not db_path:
        return {**deny, "reason": "немає db_path"}
    from office_desk_card import list_confirmed_open_positions

    want = str(symbol or "").upper()
    side = str(direction or "").upper()
    for p in list_confirmed_open_positions(db_path) or []:
        if str(p.get("symbol") or "").upper() != want:
            continue
        if side and str(p.get("direction") or "").upper() != side:
            continue
        tid = str(p.get("trade_id") or "").strip()
        if not tid:
            continue
        return {
            "ok": True,
            "open": True,
            "trade_id": tid,
            "symbol": want,
            "direction": str(p.get("direction") or "").upper(),
            "entry": p.get("entry"),
            "sl": p.get("sl"),
            "reason": "OPEN /position",
        }
    return {**deny, "reason": "немає відкритої /position"}


def has_explicit_position(db_path: str, symbol: str, direction: str = "") -> bool:
    """Лише явний /position. CONFIRMED / WATCHING / office OPEN ≠ позиція."""
    return bool(get_explicit_open_position(db_path, symbol, direction).get("ok"))


def position_verified(*, in_position: bool, position_id: str, position_open: bool) -> bool:
    return bool(in_position) and bool(str(position_id or "").strip()) and bool(position_open)


def gate_outbound_telegram(
    *,
    intent: str = "",
    text: str = "",
    in_position: bool = False,
    position_id: str = "",
    position_open: bool = False,
    event_type: str = "",
    db_path: str = "",
    symbol: str = "",
    direction: str = "",
) -> Dict[str, Any]:
    """Право на Telegram: typed intent + актуальна /position з БД.

    Caller-прапорці in_position/is_open не є джерелом істини.
    ENTRY/ADD_ON/ZONE ніколи не стають дозволом на вхід.
    EVENT_SIGNAL_ENTRY без intent SIGNAL — fail-closed (і PNG теж).
    """
    intent_u = str(intent or "").strip().upper()
    ev = str(event_type or "").strip().upper()
    deny = {"send": False, "opens_position": False}
    entry_lang = text_grants_entry(text)
    pos_lang = text_instructs_position_change(text)

    live: Dict[str, Any] = {}
    if db_path:
        live = get_explicit_open_position(db_path, symbol, direction)
        if live.get("ok"):
            in_position = True
            position_open = True
            position_id = str(live.get("trade_id") or position_id or "")
        else:
            in_position = False
            position_open = False
    elif intent_u in (
        INTENT_POSITION,
        "TP",
        "SL",
        "TRAIL",
        "BE",
        "TP1",
        "HIT_SL",
        "HIT_TP1",
        "POSITION_MANAGE",
        "TRADE_CLOSED",
    ) or pos_lang:
        return {
            **deny,
            "reason": "POSITION_MANAGE без db_path — fail-closed, прапорці caller не діють",
        }

    verified = bool(live.get("ok")) if db_path else position_verified(
        in_position=in_position, position_id=position_id, position_open=position_open
    )

    if ev in ("SIGNAL_ENTRY", "EVENT_SIGNAL_ENTRY") or intent_u in (
        "SIGNAL",
        "LEV_SIGNAL",
        "SIGNAL_ENTRY",
    ):
        if intent_u not in ("SIGNAL", "LEV_SIGNAL"):
            return {
                **deny,
                "reason": "EVENT_SIGNAL_ENTRY без typed intent SIGNAL — fail-closed",
            }
        if pos_lang or entry_lang:
            return {**deny, "reason": "картка SIGNAL не може наказувати ордер або вхід"}
        return {
            "send": True,
            "reason": "перевірений сценарій Лева (не /position)",
            "opens_position": False,
        }

    if intent_u in (INTENT_ZONE, "ZONE_REACHED", INTENT_HIT_ENTRY, "HIT_ENTRY"):
        return {**deny, "reason": "зона/HIT_ENTRY не шле дозвіл на вхід і не супроводить позицію"}
    if intent_u in (INTENT_ENTRY, "SIGNAL_ENTRY", "MOZHNA"):
        return {**deny, "reason": "ENTRY_PERMISSION не через вільний текст"}
    if intent_u in (INTENT_ADD, "ADD", "ADD_ON", "SCALE_IN", "REVERSAL"):
        return {**deny, "reason": "добір/переворот не автоматичний у Telegram"}
    if intent_u in (INTENT_CONFIRM, "CONFIRM"):
        if entry_lang or pos_lang:
            return {**deny, "reason": "CONFIRMED-картка не може наказувати ордер"}
        return {"send": True, "reason": "підтвердження сценарію", "opens_position": False}

    manage = intent_u in (
        INTENT_POSITION,
        "TP",
        "SL",
        "TRAIL",
        "BE",
        "TP1",
        "HIT_SL",
        "HIT_TP1",
        "POSITION_MANAGE",
        "TRADE_CLOSED",
    )

    if pos_lang:
        if not verified:
            return {
                **deny,
                "reason": "наказ змінити позицію без verified OPEN /position — fail-closed",
            }
        if entry_lang:
            return {**deny, "reason": "супровід /position не дає нового входу"}
        if not manage:
            return {
                **deny,
                "reason": "немає типу події POSITION_MANAGE — fail-closed",
            }
        return {
            "send": True,
            "reason": "супровід verified OPEN /position",
            "opens_position": False,
            "position_id": str(position_id),
        }

    if entry_lang:
        return {**deny, "reason": "мова входу/добору заборонена"}

    if intent_u in (INTENT_POSITION, "POSITION_MANAGE", "TP", "SL", "TRAIL", "BE", "TP1", "HIT_SL"):
        if not verified:
            return {**deny, "reason": "POSITION_MANAGE без verified OPEN /position"}
        return {"send": True, "reason": "супровід verified OPEN /position", "opens_position": False}

    if intent_u in ("ANALYTICAL", "CONFIRM", "") or not intent_u:
        if pos_lang:
            return {**deny, "reason": "аналітика без наказу змінити позицію"}
        return {"send": True, "reason": "аналітичне/звичайне повідомлення", "opens_position": False}

    return {**deny, "reason": f"невідомий intent {intent_u}"}


def chase_blocks_entry(*, direction: str, price: Any, zone_lo: Any, zone_hi: Any) -> bool:
    px, lo, hi = _f(price), _f(zone_lo), _f(zone_hi)
    if px is None or lo is None or hi is None:
        return False
    if lo > hi:
        lo, hi = hi, lo
    side = str(direction or "").upper()
    if side == "LONG" and px > hi:
        return True
    if side == "SHORT" and px < lo:
        return True
    return False


def validate_trade_geometry(
    *,
    direction: str,
    sl: Any,
    tp1: Any = None,
    entry: Any = None,
    entry_low: Any = None,
    entry_high: Any = None,
    tp2: Any = None,
    require_tp: bool = True,
) -> Dict[str, Any]:
    """Fail-closed: LONG SL нижче зони входу, SHORT SL вище. Без «виправлення» рівнів."""
    side = str(direction or "").upper()
    deny = {"ok": False, "send": False, "opens_position": False, "size_allowed": False}
    s, t1, t2 = _f(sl), _f(tp1), _f(tp2)
    e = _f(entry)
    lo, hi = _f(entry_low), _f(entry_high)
    if lo is None:
        lo = e
    if hi is None:
        hi = e
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    if side not in ("LONG", "SHORT"):
        return {**deny, "reason": "немає напрямку"}
    if s is None or lo is None or hi is None:
        return {**deny, "reason": "немає зони/SL"}
    if side == "LONG":
        if s >= lo - 1e-18:
            return {
                **deny,
                "reason": "LONG SL не нижче нижньої межі entry-зони — картку не шлемо",
                "zone_lo": lo,
                "zone_hi": hi,
                "sl": s,
            }
        risk = lo - s
        if t1 is None:
            if require_tp:
                return {**deny, "reason": "немає TP1", "sl": s}
            return {
                "ok": True,
                "send": False,
                "size_allowed": False,
                "reason": "SL vs зона ок, TP не перевірено",
                "risk": risk,
                "zone_lo": lo,
                "zone_hi": hi,
                "sl": s,
                "opens_position": False,
            }
        if t1 <= hi:
            return {**deny, "reason": "LONG TP1 не вище верхньої межі зони", "sl": s}
        reward = t1 - hi
        if t2 is not None and t2 <= t1:
            return {**deny, "reason": "LONG TP2 не далі за TP1", "sl": s}
    else:
        if s <= hi + 1e-18:
            return {
                **deny,
                "reason": "SHORT SL не вище верхньої межі entry-зони — картку не шлемо",
                "zone_lo": lo,
                "zone_hi": hi,
                "sl": s,
            }
        risk = s - hi
        if t1 is None:
            if require_tp:
                return {**deny, "reason": "немає TP1", "sl": s}
            return {
                "ok": True,
                "send": False,
                "size_allowed": False,
                "reason": "SL vs зона ок, TP не перевірено",
                "risk": risk,
                "zone_lo": lo,
                "zone_hi": hi,
                "sl": s,
                "opens_position": False,
            }
        if t1 >= lo:
            return {**deny, "reason": "SHORT TP1 не нижче нижньої межі зони", "sl": s}
        reward = lo - t1
        if t2 is not None and t2 >= t1:
            return {**deny, "reason": "SHORT TP2 не далі за TP1", "sl": s}
    if risk <= 0:
        return {**deny, "reason": "дистанція ризику не додатна — abs() не ховає стоп з неправильного боку"}
    rr = reward / risk if risk else 0.0
    if rr + 1e-12 < MIN_RR:
        return {**deny, "reason": f"RR {rr:.2f} < {MIN_RR} (знаковий ризик)", "rr": rr, "sl": s}
    return {
        "ok": True,
        "send": True,
        "reason": "геометрія валідна",
        "size_allowed": True,
        "risk": risk,
        "reward": reward,
        "rr": rr,
        "zone_lo": lo,
        "zone_hi": hi,
        "sl": s,
        "opens_position": False,
    }


def scale_in_review(
    *,
    in_position: bool,
    geometry_ok: bool = False,
    setup_valid: bool = False,
    owner_confirmed: bool = False,
) -> Dict[str, Any]:
    """Добір ніколи не ордер. Без /position — заборона. З /position — лише план."""
    deny = {"ok": False, "order": False, "telegram": False, "plan_only": False}
    if not in_position:
        return {**deny, "reason": "немає явного /position — добір заборонено"}
    if not geometry_ok:
        return {**deny, "reason": "геометрія невалідна — добір заборонено"}
    if not setup_valid:
        return {**deny, "reason": "сетап не чинний — добір заборонено"}
    if not owner_confirmed:
        return {
            **deny,
            "plan_only": True,
            "reason": "є /position: лише план зміни ризику, потрібне підтвердження Тетяни",
        }
    return {
        "ok": False,
        "order": False,
        "telegram": False,
        "plan_only": True,
        "reason": "підтверджений план без ордера",
    }


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
