"""Хто має право на торгове рішення. Лев — єдине джерело SIGNAL.

Модулі можуть створювати MARKET_FACT і кандидата. Не створюють ENTER.
Не змінює ATR 80/90, Edge 85, MIN_RR 1.5. Не ордер.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Set

# Ролі модулів: факт / кандидат / сценарій / дозвіл / супровід позиції.
MODULE_ROLE: Dict[str, str] = {
    "market_scout": "FACT",
    "radar": "CANDIDATE",
    "pump_dump": "INDICATOR",
    "ict_hunter": "INDICATOR",
    "regression_channel": "INDICATOR",
    "t0": "FACT",
    "follow": "LIFECYCLE",
    "steer": "POSITION_ONLY",
    "llm": "NARRATIVE",
    "desk": "SCENARIO_INPUT",
    "lev_cycle": "DECISION",
    "outbound_gate": "SEND",
    "mini_app": "READONLY",
}

FACT_ONLY: Set[str] = {
    "radar",
    "pump_dump",
    "ict_hunter",
    "regression_channel",
    "t0",
    "llm",
    "market_scout",
}

STATUSES_HAD_ENTRY = frozenset({"HIT_ENTRY", "HIT_TP1", "HIT_TP2", "HIT_TP3"})
STATUSES_SCENARIO = frozenset(
    {
        "FOUND",
        "WATCHING",
        "ACTIVE",
        "ZONE_REACHED",
        "CONFIRMATION_PENDING",
        "CONFIRMED",
        "EXPIRED",
        "INVALIDATED",
        "HIT_SL",
        "CANCELLED",
    }
)


def module_may_create_signal(module: str, *, lev_cycle_ok: bool = False) -> bool:
    """Лише повний цикл Лева дає SIGNAL. Індикатор/радар/T0/LLM — ні."""
    src = str(module or "").strip().lower()
    if src in FACT_ONLY:
        return False
    if src in ("follow", "steer"):
        return False
    if src in ("lev", "lev_cycle", "desk"):
        return bool(lev_cycle_ok)
    return False


def indicator_creates_enter() -> bool:
    return False


def confirmed_is_open_position() -> bool:
    """CONFIRMED сценарію ≠ OPEN /position."""
    return False


def cancelled_before_entry_is_position_close() -> bool:
    return False


def had_confirmed_entry(status: Any) -> bool:
    return str(status or "").upper() in STATUSES_HAD_ENTRY


def reentry_label_allowed(*, previous_status: Any, previous_had_position: bool = False) -> bool:
    """«Повторний вхід» лише після фактичного входу або явної /position."""
    return bool(previous_had_position) or had_confirmed_entry(previous_status)


def cancel_before_entry_text(*, symbol: str, direction: str, reason: str = "") -> str:
    why = str(reason or "").strip() or "DATA_UNAVAILABLE"
    return (
        f"❌ {str(symbol).upper()} {str(direction or '').upper()} · "
        f"скасовано: ціна за стопом до входу. {why}. Це скасування сценарію, не закриття позиції."
    )


def recommend_close_text(*, symbol: str, price: Any, sl: Any) -> str:
    from office_price_format import format_px

    sym = str(symbol or "").upper()
    return (
        f"Тетяно, {sym}: SL позиції перебитий на {format_px(sl, sym)} "
        f"(ціна {format_px(price, sym)}).\n"
        f"Що робити зараз: рекомендую повний вихід з позиції зараз.\n"
        f"Факт закриття: чекаю явного оновлення /position — не пишу «позиція закрита»."
    )


def previous_to_new_link(
    *,
    prev_direction: str = "LONG",
    prev_status: str = "",
    reason: str = "",
    new_tf: str = "H1",
    wait_for: str = "відкат і LTF-підтвердження",
    had_entry: bool = False,
) -> str:
    why = str(reason or "").strip()
    side = str(prev_direction or "LONG").upper()
    tf = str(new_tf or "H1").upper()
    wait = str(wait_for or "відкат").strip()
    if had_entry:
        return (
            f"Попередній {side} мав підтверджений вхід (статус {prev_status or '—'}). "
            f"Новий сценарій {tf} очікує {wait}."
        )
    if not why or why.upper() == "DATA_UNAVAILABLE":
        return (
            f"Попередній {side} скасовано до входу. Причину Live не підтверджено (DATA_UNAVAILABLE). "
            f"Новий сценарій {tf} очікує {wait}."
        )
    return (
        f"Попередній {side} скасовано до входу: {why}. "
        f"Новий сценарій {tf} очікує {wait}."
    )


def status_after_cancel_new_setup() -> str:
    return "WATCHING"


def scenario_sl_may_override_position_sl() -> bool:
    return False
