"""TTL 2.0: сценарій живе, поки жива ідея. Годинник — лише верхня межа; знімають причини (закриття H1 за рівнем скасування, злам
структури H1, ціль без входу, ціна за межею входу). Меж: M15 і молодші — до кінця НАСТУПНОЇ сесії (сценарій з Азії переживає
Лондон); H1 — 24 год; H4 — 48 год; D1 — 5 діб. Сесії (UTC, наближено, без переходу на літній час — окремий пункт плану): Азія 00–08, Лондон 07–16, Нью-Йорк 12–21."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple

SESSIONS_UTC = (("ASIA", 0, 8), ("LONDON", 7, 16), ("NY", 12, 21))
HOURS = {"H1": 24, "1H": 24, "H4": 48, "4H": 48, "D1": 24 * 5, "1D": 24 * 5}


def _intervals(ts: float) -> List[Tuple[float, float]]:
    d0 = datetime.fromtimestamp(ts, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for k in (-1, 0, 1, 2):
        day = d0 + timedelta(days=k)
        for _n, a, b in SESSIONS_UTC:
            out.append(((day + timedelta(hours=a)).timestamp(), (day + timedelta(hours=b)).timestamp()))
    return sorted(out)


def next_session_end(ts: float) -> float:
    """Кінець першої сесії, що ПОЧИНАЄТЬСЯ після ts (Азія → переживає Лондон)."""
    for start, end in _intervals(ts):
        if start > ts:
            return end
    return ts + 24 * 3600


def deadline(ts: float, tf: Any = "H1") -> float:
    t = str(tf or "H1").upper()
    h = HOURS.get(t)
    return float(ts) + h * 3600 if h else next_session_end(float(ts))


def is_time_expired(ts: float, tf: Any, now: float) -> bool:
    return now >= deadline(ts, tf)
