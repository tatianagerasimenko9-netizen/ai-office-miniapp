"""T2 Назар: fail-closed новини. Не рішення Лева і не ордер.

Немає API / timeout / помилка → мовчання (None).
Є відповідь, подій немає → нейтральна фраза без «входити можна».
Подія в наступні 60 хв → попередження з назвою і часом.
"""
from __future__ import annotations

from typing import Any, Optional

DATA_OK = "DATA_OK"
DATA_EMPTY = "DATA_EMPTY"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
WARN_WINDOW_MIN = 60
NEUTRAL_UA = "📰 Новин немає. Фон нейтральний."
FORBIDDEN = ("входити можна", "фон чистий", "новинний фон чистий")


def _clean(s: Any) -> str:
    return str(s or "").strip()


def format_nazar_update(
    *,
    data_status: Any,
    minutes_to_event: Any = None,
    event_name: Any = "",
    event_time_ua: Any = "",
) -> Optional[str]:
    """Текст Назара або None (не слати в Telegram)."""
    st = str(data_status or "").upper()
    if st in ("DATA_UNAVAILABLE", "UNAVAILABLE", "ERROR", "TIMEOUT"):
        return None
    try:
        mins = int(minutes_to_event) if minutes_to_event is not None else 999
    except (TypeError, ValueError):
        mins = 999
    name = _clean(event_name)
    when = _clean(event_time_ua) or "н/д"
    if name and 0 <= mins <= WARN_WINDOW_MIN:
        return f"📰 УВАГА: {name} о {when}. Можлива волатильність."
    if st in (DATA_EMPTY, "EMPTY") or mins >= 999 or not name:
        return NEUTRAL_UA
    return f"📰 УВАГА: {name} о {when}. Можлива волатильність."


def nazar_is_silent(text: Optional[str]) -> bool:
    return text is None or not str(text).strip()


def nazar_forbidden_in(text: Any) -> bool:
    blob = str(text or "").lower()
    return any(p in blob for p in FORBIDDEN)
