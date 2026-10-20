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

def pre_session_range(bars: Sequence[Mapping[str,Any]], *, asof_ts:float,
                      name:str, minutes:int=60) -> dict[str,Any]:
    """Research-only pre-session range, ending at local session start.

    Requires complete M15 coverage of the pre-session window. Missing candles
    return no levels rather than an apparently valid partial range.
    """
    from datetime import timedelta
    if name not in WINDOWS: raise ValueError("unknown session")
    if minutes<=0 or minutes%15: raise ValueError("minutes must be positive multiple of 15")
    zone,start,_=WINDOWS[name]
    local_now=datetime.fromtimestamp(asof_ts,timezone.utc).astimezone(ZoneInfo(zone))
    local_start=datetime.combine(local_now.date(),start,tzinfo=ZoneInfo(zone))
    start_utc=local_start.astimezone(timezone.utc).timestamp()
    end_utc=start_utc
    begin_utc=(local_start-timedelta(minutes=minutes)).astimezone(timezone.utc).timestamp()
    expected={begin_utc+900*i for i in range(minutes//15)}
    selected={}
    invalid=False
    for b in bars:
        stamp=float(b["ts"])
        if stamp in expected and stamp+900<=asof_ts:
            if stamp in selected: invalid=True
            selected[stamp]=b
            try:
                hi,lo=float(b["high"]),float(b["low"])
                if not (0<lo<=hi): invalid=True
            except (TypeError,ValueError,KeyError):
                invalid=True
    complete=(local_now.weekday()<5 and asof_ts>=end_utc
              and len(selected)==len(expected) and not invalid)
    return {"session":name,"date":local_now.date().isoformat(),
            "high":max(float(b["high"]) for b in selected.values()) if complete else None,
            "low":min(float(b["low"]) for b in selected.values()) if complete else None,
            "complete":complete,"closed_bars":len(selected),
            "expected_bars":len(expected),"mode":"SHADOW_ONLY",
            "method":"PRE_SESSION_COMPLETE_CLOSED_M15"}
