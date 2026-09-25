"""T8: життєвий цикл сетапу. Не змінює evaluate_radar і не відкриває ордери.

Стани: WATCHING → ZONE_REACHED → CONFIRMED | INVALIDATED | EXPIRED.
CONFIRMED = картка сетапу після зони й підтвердження, не позиція в журналі.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from office_session_radar import independent_flip_ok
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT, price_in_watching_zone

STATES = ("WATCHING", "ZONE_REACHED", "CONFIRMED", "INVALIDATED", "EXPIRED")
WATCHING_EXPIRE_SEC = 4 * 3600
KIND_LIFECYCLE = "lifecycle"


def _ts(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v or "").replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class LifecycleStep:
    ts: str
    state: str
    reason: str
    session: str = ""
    setup_type: str = ""
    direction: str = ""


@dataclass
class LifecycleTrace:
    symbol: str
    steps: List[LifecycleStep] = field(default_factory=list)
    next_opportunity: Optional[Dict[str, Any]] = None
    opens_position: bool = False
    kind: str = KIND_LIFECYCLE

    @property
    def terminal(self) -> str:
        if not self.steps:
            return ""
        return self.steps[-1].state


def age_sec(created: Any, now: Any) -> Optional[float]:
    a, b = _ts(created), _ts(now)
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


def next_lifecycle_state(
    *,
    current: str,
    price: Any,
    entry_low: Any,
    entry_high: Any = None,
    created_ts: Any = None,
    now_ts: Any = None,
    confirmed: bool = False,
    entry_blocked: bool = False,
    day_used_pct: Any = None,
    invalidated: bool = False,
    invalidate_reason: str = "",
) -> Dict[str, str]:
    """Один крок. CONFIRMED не означає ордер."""
    cur = str(current or "WATCHING").upper()
    if cur in ("CONFIRMED", "INVALIDATED", "EXPIRED"):
        return {"state": cur, "reason": "термінал"}
    now = now_ts
    age = age_sec(created_ts, now)
    if age is not None and age > WATCHING_EXPIRE_SEC and cur == "WATCHING":
        return {"state": "EXPIRED", "reason": "WATCHING старший за 4 год без зони"}
    in_zone = price_in_watching_zone(price, entry_low, entry_high)
    if cur == "WATCHING":
        if not in_zone:
            return {"state": "WATCHING", "reason": "ціна поза зоною — чекаємо"}
        if invalidated:
            return {"state": "INVALIDATED", "reason": invalidate_reason or "структура зламалась"}
        return {"state": "ZONE_REACHED", "reason": "ціна в зоні очікування"}
    if cur == "ZONE_REACHED":
        try:
            used = float(day_used_pct) if day_used_pct is not None else None
        except (TypeError, ValueError):
            used = None
        if used is not None and used > ATR_DAY_USED_ENTRY_BLOCK_PCT:
            return {
                "state": "EXPIRED",
                "reason": f"ZONE_REACHED, ATR>{ATR_DAY_USED_ENTRY_BLOCK_PCT:.0f}% — вхід заблоковано T0",
            }
        if invalidated:
            return {"state": "INVALIDATED", "reason": invalidate_reason or "зона досягнута, тезу знято"}
        if confirmed and not entry_blocked:
            return {"state": "CONFIRMED", "reason": "підтвердження малого ТФ — картка, не ордер"}
        if not in_zone:
            return {"state": "WATCHING", "reason": "ціна вийшла з зони до підтвердження"}
        return {"state": "ZONE_REACHED", "reason": "в зоні, підтвердження ще немає"}
    return {"state": cur, "reason": "без зміни"}


def flip_invalidates(
    *,
    previous_direction: str,
    new_direction: str,
    sweep: Dict[str, Any],
    m5_ok: bool,
    m1_ok: bool,
    stop_hit: bool,
) -> bool:
    """True, якщо напрямок змінився без незалежного підтвердження."""
    prev = str(previous_direction or "").upper()
    nxt = str(new_direction or "").upper()
    if not prev or not nxt or prev == nxt:
        return False
    return not independent_flip_ok(
        previous_direction=prev,
        new_direction=nxt,
        sweep=sweep or {},
        m5_ok=m5_ok,
        m1_ok=m1_ok,
        stop_hit=stop_hit,
    )


def remaining_pct(*, price: Any, target: Any) -> Optional[float]:
    try:
        p, t = float(price), float(target)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    return abs(t - p) / p * 100.0


def format_manage_update(
    *,
    symbol: str,
    direction: str,
    price: Any,
    tp1: Any,
    sl: Any,
    remaining_to_tp1: Any = None,
) -> str:
    """Оновлення до TP1. Не відкриває угоду."""
    from office_telegram_filter import format_px

    side = str(direction or "").upper()
    left = remaining_to_tp1
    if left is None:
        left = remaining_pct(price=price, target=tp1)
    left_s = f"{float(left):.1f}%" if left is not None else "н/д"
    return "\n".join(
        [
            f"📍 UPDATE · {symbol} {side}",
            f"Ціна зараз: {format_px(price)}",
            f"TP1 близько ({format_px(tp1)} — залишилось {left_s})",
            "→ Готуйся закрити 50–70% на TP1",
            f"→ SL тримай на {format_px(sl)} поки не закрито TP1",
        ]
    )


def format_tp1_hit(
    *,
    symbol: str,
    direction: str,
    entry: Any,
    tp1: Any,
    tp2: Any = None,
    move_pct: Any = None,
) -> str:
    """TP1 взято: конкретні дії. Не ордер у біржі."""
    from office_telegram_filter import format_px, move_pct_to_tp

    side = str(direction or "").upper()
    mv = move_pct
    if mv is None:
        mv = move_pct_to_tp(entry=entry, tp=tp1)
    mv_s = f"+{float(mv):.1f}%" if mv is not None else ""
    lines = [
        f"✅ TP1 · {symbol} {side}" + (f" · {mv_s}" if mv_s else ""),
        "Закрий 50–70% позиції зараз",
        f"Перестав SL в беззбиток: {format_px(entry)}",
    ]
    if format_px(tp2):
        lines.append(f"Тримай решту до TP2 ({format_px(tp2)})")
    return "\n".join(lines)


def record_next_opportunity(
    trace: LifecycleTrace,
    *,
    ts: str,
    setup_type: str,
    direction: str,
    session: str,
    reason: str,
) -> None:
    """Після SKIP/EXPIRED/INVALIDATED радар може відкрити новий слід."""
    if trace.next_opportunity:
        return
    trace.next_opportunity = {
        "ts": ts,
        "setup_type": setup_type,
        "direction": direction,
        "session": session,
        "reason": reason,
        "kind": KIND_LIFECYCLE,
        "opens_position": False,
    }
