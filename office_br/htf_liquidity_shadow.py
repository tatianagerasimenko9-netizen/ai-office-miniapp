"""Causal B&R HTF liquidity levels; research only, no order execution.

Returns only complete, strictly closed historical bars. Confirmed pivots
require right-side candles that were already closed by the decision time.
"""
from __future__ import annotations
from math import isfinite
from typing import Any,Mapping,Sequence

SECONDS={"1M":None,"1w":None,"1d":86400,"4h":14400,"1h":3600}
def levels(bars:Sequence[Mapping[str,Any]],*,timeframe:str,asof_ts:float,
           left:int=2,right:int=2)->dict[str,Any]:
    if timeframe not in SECONDS:raise ValueError("timeframe")
    if left<1 or right<1:raise ValueError("pivot windows")
    valid=[]
    for b in bars:
        try:
            opened=float(b["ts"])
            closed=(float(b["close_ts"]) if timeframe in ("1M","1w")
                    else opened+SECONDS[timeframe])
            high=float(b["high"]);low=float(b["low"])
            if not all(isfinite(x) for x in (opened,closed,high,low)) or not (0<low<=high):
                raise ValueError("bad candle")
            if closed<=opened or closed>asof_ts:continue
            valid.append({"ts":opened,"closed":closed,"high":high,"low":low})
        except (KeyError,ValueError,TypeError):
            return {"timeframe":timeframe,"mode":"SHADOW_ONLY","complete":False,
                    "high":None,"low":None,"pivots_high":[],"pivots_low":[]}
    valid.sort(key=lambda x:x["ts"])
    if len(valid)<left+right+1 or any(valid[i]["ts"]<=valid[i-1]["ts"] for i in range(1,len(valid))):
        return {"timeframe":timeframe,"mode":"SHADOW_ONLY","complete":False,
                "high":None,"low":None,"pivots_high":[],"pivots_low":[]}
    ph=[];pl=[]
    for i in range(left,len(valid)-right):
        b=valid[i]
        surrounding=valid[i-left:i]+valid[i+1:i+right+1]
        if all(b["high"]>x["high"] for x in surrounding):
            ph.append({"price":b["high"],"pivot_ts":b["ts"],
                       "confirmed_ts":valid[i+right]["closed"]})
        if all(b["low"]<x["low"] for x in surrounding):
            pl.append({"price":b["low"],"pivot_ts":b["ts"],
                       "confirmed_ts":valid[i+right]["closed"]})
    return {"timeframe":timeframe,"mode":"SHADOW_ONLY","complete":True,
            "high":max(b["high"] for b in valid),"low":min(b["low"] for b in valid),
            "pivots_high":ph,"pivots_low":pl,
            "closed_bars":len(valid),"asof_ts":asof_ts}
