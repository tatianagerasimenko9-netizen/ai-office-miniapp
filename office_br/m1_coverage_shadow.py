"""Strict B&R historical M1 completeness audit, without altering replay results."""
from __future__ import annotations
from math import isfinite
from typing import Any,Mapping,Sequence

def audit_m1(bars:Sequence[Mapping[str,Any]],*,start_ts:float,end_ts:float)->dict[str,Any]:
    if not all(isfinite(float(x)) for x in (start_ts,end_ts)) or end_ts<=start_ts:
        raise ValueError("invalid range")
    if start_ts%60 or end_ts%60:raise ValueError("unaligned range")
    expected=int((end_ts-start_ts)//60)
    if expected!=(end_ts-start_ts)/60:raise ValueError("unaligned duration")
    seen=set()
    invalid=0;duplicate=0;outside=0
    for b in bars:
        try:
            ts=float(b["ts"])
            o,h,l,c=(float(b[k]) for k in ("open","high","low","close"))
            if not all(isfinite(x) for x in (ts,o,h,l,c)) or ts%60 or not (0<l<=min(o,c)<=max(o,c)<=h):
                invalid+=1;continue
            if not start_ts<=ts<end_ts:outside+=1;continue
            if ts in seen:duplicate+=1
            seen.add(ts)
        except (KeyError,ValueError,TypeError,OverflowError):
            invalid+=1
    missing=expected-len(seen)
    return {"complete":missing==0 and invalid==0 and duplicate==0 and outside==0,
            "expected":expected,"observed_unique":len(seen),"missing":missing,
            "invalid":invalid,"duplicate":duplicate,"outside":outside,
            "mode":"SHADOW_ONLY"}
