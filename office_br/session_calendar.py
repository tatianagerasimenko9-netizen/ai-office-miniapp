"""Calendar-aware US equity phases for B&R research. No trading decisions.

Classifies event timestamps, not Binance market hours. US federal holidays are
not inferred: weekday regular hours are *scheduled*, not verified open.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
KYIV = ZoneInfo("Europe/Kyiv")


def classify_us_equity_clock(timestamp: float) -> dict[str, object]:
    """Return DST-aware scheduled phase, distinguishing weekends from weekdays.

    Holidays/half-days are intentionally UNVERIFIED. No live gate is applied.
    """
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(NY)
    minutes = dt.hour * 60 + dt.minute
    if dt.weekday() >= 5:
        phase = "WEEKEND"
    elif 4 * 60 <= minutes < 9 * 60 + 30:
        phase = "PREMARKET"
    elif 9 * 60 + 30 <= minutes < 16 * 60:
        phase = "REGULAR"
    elif 16 * 60 <= minutes < 20 * 60:
        phase = "AFTERHOURS"
    else:
        phase = "OVERNIGHT"
    return {
        "phase": phase,
        "new_york_date": dt.date().isoformat(),
        "new_york_time": dt.strftime("%H:%M"),
        "new_york_weekday": dt.weekday(),
        "kyiv_time": datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(KYIV).isoformat(),
        "calendar_verified": False,
        "scope": "SHADOW_ONLY",
    }
