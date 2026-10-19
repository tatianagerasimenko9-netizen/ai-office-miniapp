"""B&R-only session context: DST-aware clock and closed-candle session levels.

Reference windows are explicit UTC-local market clocks, NOT claims about
exchange premarket or a blogger's methodology. Shadow diagnostics only.
"""
from __future__ import annotations
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from typing import Any, Mapping, Sequence

WINDOWS = {
    "ASIA": ("Asia/Tokyo", time(9), time(15)),
    "LONDON": ("Europe/London", time(8), time(16)),
    "NEW_YORK": ("America/New_York", time(9,30), time(16)),
}

def sessions_at(ts: float) -> list[str]:
    instant = datetime.fromtimestamp(ts,timezone.utc)
    active=[]
    for name,(zone,start,end) in WINDOWS.items():
        local=instant.astimezone(ZoneInfo(zone))
        if local.weekday()<5 and start<=local.time().replace(tzinfo=None)<end:
            active.append(name)
    return active

def closed_session_range(bars: Sequence[Mapping[str,Any]], *, asof_ts:float,
                         name:str) -> dict[str,Any]:
    """Compute only bars strictly closed before asof_ts and inside the same local session date."""
    if name not in WINDOWS: raise ValueError("unknown session")
    zone,start,end=WINDOWS[name]
    now=datetime.fromtimestamp(asof_ts,timezone.utc).astimezone(ZoneInfo(zone))
    used=[]
    for b in bars:
        ts=float(b["ts"])
        # M15 candles are timestamped by OPEN. Never use an unclosed bar.
        if ts+900>asof_ts: continue
        local=datetime.fromtimestamp(ts,timezone.utc).astimezone(ZoneInfo(zone))
        if local.date()!=now.date() or local.weekday()>=5: continue
        if start<=local.time().replace(tzinfo=None)<end:
            used.append(b)
    return {"session":name,"local_date":now.date().isoformat(),
            "high":max(float(x["high"]) for x in used) if used else None,
            "low":min(float(x["low"]) for x in used) if used else None,
            "closed_bars":len(used),"asof_ts":asof_ts,
            "mode":"SHADOW_ONLY","method":"LOCAL_SESSION_CLOSED_M15"}
