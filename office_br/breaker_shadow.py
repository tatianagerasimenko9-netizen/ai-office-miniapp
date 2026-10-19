"""B&R breaker candidate: invalidated order-block zone, research only.

A breaker is not declared until a later CLOSED candle breaks through the
entire candidate OB zone. This is an explicit research hypothesis, not a
claim about a named author's canonical definition.
"""
from __future__ import annotations
from math import isfinite
from typing import Any,Mapping,Sequence

def breakers(blocks:Sequence[Mapping[str,Any]],bars:Sequence[Mapping[str,Any]],
             *,asof_ts:float)->list[dict[str,Any]]:
    result=[]
    for ob in blocks:
        try:
            lo=float(ob["low"]);hi=float(ob["high"])
            formed=float(ob["confirmed_ts"]);side=str(ob["direction"]).upper()
            if not (isfinite(lo) and isfinite(hi) and isfinite(formed)
                    and 0<lo<hi and side in ("LONG","SHORT")):
                continue
            for bar in sorted(bars,key=lambda x:float(x["ts"])):
                opened=float(bar["ts"]);closed=float(bar["close_ts"])
                price=float(bar["close"])
                if not all(isfinite(v) for v in (opened,closed,price)):
                    continue
                if opened<formed or closed<=opened or closed>asof_ts:
                    continue
                invalidated=(price<lo if side=="LONG" else price>hi)
                if invalidated:
                    result.append({"type":"BREAKER_CANDIDATE",
                                   "direction":"SHORT" if side=="LONG" else "LONG",
                                   "zone_low":lo,"zone_high":hi,
                                   "source_ob_confirmed_ts":formed,
                                   "confirmed_ts":closed,"mode":"SHADOW_ONLY"})
                    break
        except (KeyError,ValueError,TypeError):
            continue
    return result
