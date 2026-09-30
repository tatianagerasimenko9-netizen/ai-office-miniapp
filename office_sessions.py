"""Торгові сесії з автоматичним переходом на літній/зимовий час і маніпуляційні вікна перед відкриттям.

Азія — 00:00–08:00 UTC (у Азії літнього часу немає); Лондон — 08:00–16:00 за Лондоном (Europe/London); Нью-Йорк — 08:00–16:00 за Нью-Йорком
(America/New_York). Переходи на DST (різні дати в Європі й США) враховує zoneinfo. Маніпуляційне вікно — 30 хв ДО відкриття кожної сесії
(типові хибні рухи перед відкриттям): у ньому підтвердження входу не приймаємо як чисте (див. `manipulation_window`)."""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
MANIP_MIN = 30
# (назва, зона або None = UTC, початок, кінець — локальний час)
_DEFS = (("ASIA", None, dtime(0, 0), dtime(8, 0)), ("LONDON", LONDON, dtime(8, 0), dtime(16, 0)), ("NY", NEW_YORK, dtime(8, 0), dtime(16, 0)))


def _utc(d: date, t: dtime, tz: Optional[ZoneInfo]) -> datetime:
    naive = datetime.combine(d, t)
    return naive.replace(tzinfo=tz or timezone.utc).astimezone(timezone.utc)


def intervals_utc(d: date) -> List[Tuple[str, datetime, datetime]]:
    """Сесії календарної дати d (локальної для кожної сесії) у UTC."""
    out = []
    for name, tz, a, b in _DEFS:
        out.append((name, _utc(d, a, tz), _utc(d, b, tz)))
    return out


def all_intervals(ts: float, days: Tuple[int, ...] = (-1, 0, 1, 2)) -> List[Tuple[str, float, float]]:
    d0 = datetime.fromtimestamp(ts, tz=timezone.utc).date()
    res = []
    for k in days:
        for name, a, b in intervals_utc(d0 + timedelta(days=k)):
            res.append((name, a.timestamp(), b.timestamp()))
    return sorted(res, key=lambda x: x[1])


def active_sessions(ts: float) -> List[str]:
    return [n for n, a, b in all_intervals(ts) if a <= ts < b]


def manipulation_window(ts: float) -> Optional[str]:
    """Назва сесії, до відкриття якої лишилося < MANIP_MIN хв (маніпуляційне вікно), інакше None."""
    for name, a, _b in all_intervals(ts):
        if 0 < a - ts <= MANIP_MIN * 60:
            return name
    return None


def next_session_end(ts: float) -> float:
    """Кінець першої сесії, що ПОЧИНАЄТЬСЯ після ts."""
    for _n, a, b in all_intervals(ts):
        if a > ts:
            return b
    return ts + 24 * 3600
