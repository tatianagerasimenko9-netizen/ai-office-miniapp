"""TTL 2.0: сценарій живе, поки жива ідея. Годинник — лише верхня межа; знімають причини (закриття H1 за рівнем скасування, злам
структури H1, ціль без входу, ціна за межею входу). Меж: M15 і молодші — до кінця НАСТУПНОЇ сесії (сценарій з Азії переживає
Лондон); H1 — 24 год; H4 — 48 год; D1 — 5 діб. Сесії — `office_sessions` (Лондон і Нью-Йорк за місцевим часом, DST враховано)."""
from __future__ import annotations

from typing import Any

HOURS = {"H1": 24, "1H": 24, "H4": 48, "4H": 48, "D1": 24 * 5, "1D": 24 * 5}


def next_session_end(ts: float) -> float:
    """Кінець першої сесії, що ПОЧИНАЄТЬСЯ після ts (Азія → переживає Лондон). Сесії — office_sessions (з переходом на літній/зимовий час)."""
    from office_sessions import next_session_end as _n

    return _n(ts)


def deadline(ts: float, tf: Any = "H1") -> float:
    t = str(tf or "H1").upper()
    h = HOURS.get(t)
    return float(ts) + h * 3600 if h else next_session_end(float(ts))


def is_time_expired(ts: float, tf: Any, now: float) -> bool:
    return now >= deadline(ts, tf)
