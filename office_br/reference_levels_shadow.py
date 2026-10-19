"""B&R-only causal previous-day/week highs and lows from closed M15 candles.

Uses UTC calendar boundaries explicitly; not a substitute for exchange/session
local calendar definitions. Never uses the current incomplete day/week.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from typing import Any,Mapping,Sequence

def reference_levels(bars:Sequence[Mapping[str,Any]],*,asof_ts:float,
                     candle_seconds:int=900)->dict[str,Any]:
    now=datetime.fromtimestamp(asof_ts,timezone.utc)
    day_start=now.replace(hour=0,minute=0,second=0,microsecond=0)
    prev_day=day_start-timedelta(days=1)
    week_start=day_start-timedelta(days=day_start.weekday())
    prev_week=week_start-timedelta(days=7)
    intervals={"PD":(prev_day,day_start),"PW":(prev_week,week_start)}
    out={"mode":"SHADOW_ONLY","calendar":"UTC","asof_ts":asof_ts}
    for key,(start,end) in intervals.items():
        candles=[b for b in bars if start.timestamp()<=float(b["ts"]) and
                 float(b["ts"])+candle_seconds<=min(end.timestamp(),asof_ts)]
        out[key+"H"]=max(float(b["high"]) for b in candles) if candles else None
        out[key+"L"]=min(float(b["low"]) for b in candles) if candles else None
        out[key+"_closed_bars"]=len(candles)
        out[key+"_complete"]=(len(candles)==int((end-start).total_seconds()/candle_seconds))
    return out
