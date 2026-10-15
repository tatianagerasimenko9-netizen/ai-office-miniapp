"""Pure, fail-closed guards for live analyst signals. No order placement.

Integrate these guards at the READY emission and Telegram lifecycle boundaries.
Until integrated, this module alone DOES NOT change production behavior.
"""
from __future__ import annotations

from typing import Any, Mapping

FUTURES_SOURCES = frozenset({"binance_futures", "binance_um_futures", "binance_futures_ws", "binance_futures_rest", "binance_futures_archive"})
TERMINAL_PRE_ENTRY = frozenset({"INVALIDATED", "EXPIRED", "NO_ENTRY", "TIMEOUT"})
PROFIT_EVENTS = frozenset({"TP1", "TP2", "TP3", "SL", "BE", "PNL"})


def verified_futures_candle(candle: Mapping[str, Any], *, decision_ts: float, interval_sec: int) -> bool:
    """Accept only proven, closed, timely USD-M futures OHLCV; unknown means no READY."""
    source = str(candle.get("source") or "").lower()
    market = str(candle.get("market") or "").lower()
    try:
        ts = float(candle["ts"])
        o, h, l, c = (float(candle[k]) for k in ("open", "high", "low", "close"))
    except (KeyError, ValueError, TypeError):
        return False
    if source not in FUTURES_SOURCES or market not in {"um_futures", "usdm_futures", "usd-m_futures"}:
        return False
    if interval_sec <= 0 or ts + interval_sec > decision_ts or decision_ts - (ts + interval_sec) > interval_sec:
        return False
    if not (0 < l <= min(o, c) <= max(o, c) <= h):
        return False
    return True


def allow_lifecycle_event(card: Mapping[str, Any], event: str) -> bool:
    """No TP/PnL after invalidation before an actual confirmed entry.

    A price touching a target is not proof of a fill.
    """
    state = str(card.get("state") or card.get("paper_status") or "").upper()
    entry_confirmed = bool(card.get("entry_confirmed"))
    if event.upper() in PROFIT_EVENTS:
        return entry_confirmed and state not in TERMINAL_PRE_ENTRY
    if event.upper() == "CONFIRMED_ENTRY":
        return state not in TERMINAL_PRE_ENTRY
    return True


def public_outcome_label(card: Mapping[str, Any], event: str) -> str:
    """Prevent simulated price movement from being presented as realized profit."""
    if event.upper() in PROFIT_EVENTS and not allow_lifecycle_event(card, event):
        return "Ціна торкнулася рівня, але підтвердженого входу немає — прибуток не нараховано"
    if event.upper() in PROFIT_EVENTS and card.get("execution_mode") != "MANUAL_CONFIRMED":
        return "Навчальна симуляція, не реальний результат"
    return "Підтверджена вручну позиція"
