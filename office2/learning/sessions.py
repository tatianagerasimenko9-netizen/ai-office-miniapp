"""Торгова сесія моменту рішення (з урахуванням літнього/зимового часу). Широкі сесії за місцевим часом біржових центрів; не killzone."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LON, NYC, TOK = ZoneInfo("Europe/London"), ZoneInfo("America/New_York"), ZoneInfo("Asia/Tokyo")
PRE_MIN = 60


def _in(d: datetime, tz, h0, m0, h1, m1) -> bool:
    x = d.astimezone(tz)
    t = x.hour * 60 + x.minute
    return h0 * 60 + m0 <= t < h1 * 60 + m1


def _mins_to(d: datetime, tz, h, m):
    x = d.astimezone(tz)
    open_ = x.replace(hour=h, minute=m, second=0, microsecond=0)
    if open_ <= x:
        open_ += timedelta(days=1)
    return (open_ - x).total_seconds() / 60.0


def session_of(ts: float) -> dict:
    d = datetime.fromtimestamp(ts, timezone.utc)
    wd = d.weekday()
    lon = _in(d, LON, 8, 0, 16, 30)
    ny = _in(d, NYC, 9, 30, 16, 0)
    asia = _in(d, TOK, 9, 0, 15, 0)
    to_lon, to_ny = _mins_to(d, LON, 8, 0), _mins_to(d, NYC, 9, 30)
    if lon and ny:
        name = "LONDON_NY_OVERLAP"
    elif lon:
        name = "LONDON"
    elif ny:
        name = "NEW_YORK"
    elif asia:
        name = "ASIA"
    elif to_lon <= PRE_MIN:
        name = "PRE_LONDON"
    elif to_ny <= PRE_MIN:
        name = "PRE_NEW_YORK"
    else:
        name = "OFF_HOURS"
    return {"session": name, "weekend": wd >= 5, "min_to_london_open": round(to_lon, 1), "min_to_ny_open": round(to_ny, 1)}
