"""T0: ZONE_REACHED окремо від дозволу на вхід.

Поріг ATR той самий, що був у моніторі (`day_used_pct > 90`).
Фільтр блокує SIGNAL / заклик «входь», але не скасовує алерт про зону.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Збігається з історичним `if day_used_row > 90` у monitor_active_signals.
ATR_DAY_USED_ENTRY_BLOCK_PCT = 90.0
ZONE_REACHED_COOLDOWN_SEC = 14400
T0_PROBE_PREFIX = "T0-PROBE"


def is_t0_probe_note(analysis_note: Any) -> bool:
    """Тестовий WATCHING: лише ZONE_REACHED, без аналізу входу."""
    return str(analysis_note or "").startswith(T0_PROBE_PREFIX)


def after_zone_reached_action(*, analysis_note: Any, plan: WatchingZonePlan) -> str:
    """
    STOP — T0-PROBE: алерт уже надіслано, далі ні reanalyze, ні ACTIVE.
    EXPIRE_ATR / PROMOTE / REANALYZE / HOLD — звичайний монітор.
    """
    if is_t0_probe_note(analysis_note):
        return "STOP"
    if plan.expire_after_alert:
        return "EXPIRE_ATR"
    if plan.promote_active:
        return "PROMOTE"
    if plan.run_reanalyze:
        return "REANALYZE"
    return "HOLD"


def should_emit_zone_reached(
    last_ts: float,
    now_ts: float,
    window_sec: float = ZONE_REACHED_COOLDOWN_SEC,
) -> bool:
    """Антиспам повторних циклів монітора для того самого signal_id."""
    try:
        last = float(last_ts or 0.0)
        now = float(now_ts)
        window = float(window_sec)
    except (TypeError, ValueError):
        return True
    if last <= 0:
        return True
    return (now - last) >= window


def price_in_watching_zone(
    current_price: Any,
    entry_low: Any,
    entry_high: Any = None,
) -> bool:
    """True, якщо ціна всередині [min(low,high), max(low,high)]."""
    if current_price is None or entry_low is None:
        return False
    try:
        price = float(current_price)
        lo = float(entry_low)
        hi = float(entry_high) if entry_high is not None else lo
    except (TypeError, ValueError):
        return False
    if price <= 0:
        return False
    return min(lo, hi) <= price <= max(lo, hi)


def atr_blocks_watching_entry(day_used_pct: Any) -> bool:
    """True, якщо денний ATR вичерпано — вхід заборонено, але зона все одно рахується."""
    try:
        return float(day_used_pct or 0) > ATR_DAY_USED_ENTRY_BLOCK_PCT
    except (TypeError, ValueError):
        return False


def watching_levels_incomplete(sl: Any, tp1: Any, tp2: Any) -> bool:
    return sl is None and tp1 is None and tp2 is None


@dataclass(frozen=True)
class WatchingZonePlan:
    in_zone: bool
    entry_blocked: bool
    block_reason: str
    signal_ok: bool
    expire_after_alert: bool
    promote_active: bool
    run_reanalyze: bool
    message: str


def build_zone_reached_message(
    *,
    symbol: str,
    current_price: Any,
    entry_low: Any,
    entry_high: Any,
    day_used_pct: Any,
    entry_blocked: bool,
    block_reason: str,
    sl: Any = None,
) -> str:
    """Один алерт ZONE_REACHED. «входь» лише якщо вхід не заблоковано."""
    signal_flag = "NO" if entry_blocked else "YES"
    try:
        hi = float(entry_high) if entry_high is not None else float(entry_low)
        lo = float(entry_low)
        zone_lo, zone_hi = (min(lo, hi), max(lo, hi))
    except (TypeError, ValueError):
        zone_lo, zone_hi = entry_low, entry_high
    if day_used_pct is None:
        atr_txt = "н/д"
    else:
        try:
            atr_txt = f"{float(day_used_pct):.0f}%"
        except (TypeError, ValueError):
            atr_txt = "н/д"
    lines = [
        f"ZONE_REACHED · {symbol}",
        f"Ціна: {current_price}",
        f"Зона: {zone_lo}–{zone_hi}",
        f"ATR day_used: {atr_txt}",
        f"SIGNAL={signal_flag}",
    ]
    if sl is not None:
        lines.append(f"SL: {sl}")
    if entry_blocked:
        reason = (block_reason or "").strip() or "вхід заблоковано"
        lines.append(f"Причина: {reason}")
        lines.append("Вхід не відкриваємо. Зону досягнуто — фіксую подію.")
    else:
        lines.append("Це той відкат що чекали — входь!")
    return "\n".join(lines)


def plan_watching_zone_hit(
    *,
    current_price: Any,
    entry_low: Any,
    entry_high: Any = None,
    day_used_pct: Optional[float] = None,
    sl: Any = None,
    tp1: Any = None,
    tp2: Any = None,
    symbol: str = "",
) -> WatchingZonePlan:
    """Рішення монітора: алерт завжди при першому hit; вхід — окремо."""
    if not price_in_watching_zone(current_price, entry_low, entry_high):
        return WatchingZonePlan(
            in_zone=False,
            entry_blocked=False,
            block_reason="",
            signal_ok=False,
            expire_after_alert=False,
            promote_active=False,
            run_reanalyze=False,
            message="",
        )

    atr_block = atr_blocks_watching_entry(day_used_pct)
    incomplete = watching_levels_incomplete(sl, tp1, tp2)
    reasons: list[str] = []
    if atr_block:
        reasons.append(
            f"денний ATR > {ATR_DAY_USED_ENTRY_BLOCK_PCT:.0f}% — вхід заблоковано"
        )
    if incomplete:
        reasons.append("немає SL/TP — це не готовий вхід")
    entry_blocked = atr_block or incomplete
    block_reason = "; ".join(reasons)
    message = build_zone_reached_message(
        symbol=symbol,
        current_price=current_price,
        entry_low=entry_low,
        entry_high=entry_high,
        day_used_pct=day_used_pct,
        entry_blocked=entry_blocked,
        block_reason=block_reason,
        sl=sl,
    )
    return WatchingZonePlan(
        in_zone=True,
        entry_blocked=entry_blocked,
        block_reason=block_reason,
        signal_ok=not entry_blocked,
        expire_after_alert=atr_block,
        promote_active=not entry_blocked,
        run_reanalyze=incomplete and not atr_block,
        message=message,
    )


def zone_reached_to_telegram(plan: WatchingZonePlan) -> bool:
    """PR41: SIGNAL=NO лише БД. Готовий вхід іде як SIGNAL_ENTRY, не текст ZONE_REACHED."""
    return bool(plan.in_zone and plan.signal_ok)


def format_zone_signal_entry(
    *,
    symbol: str,
    current_price: Any,
    entry_low: Any,
    entry_high: Any,
    sl: Any,
    tp1: Any,
    tp2: Any = None,
) -> str:
    """Картка входу після готової зони (не службовий ZONE_REACHED)."""
    return (
        f"Тетяно, {symbol} підтвердив зону входу {entry_low}–{entry_high}.\n"
        f"Ціна: {current_price}. SL: {sl} · TP1: {tp1}"
        + (f" · TP2: {tp2}" if tp2 is not None else "")
        + "\nМожна входити."
    )
