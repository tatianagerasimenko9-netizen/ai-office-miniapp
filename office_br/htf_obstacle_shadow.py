"""B&R shadow-only opposing HTF liquidity distance for manual signal research."""
from __future__ import annotations
from math import isfinite
from typing import Any,Mapping

def obstacle(entry:float,direction:str,contexts:Mapping[str,Mapping[str,Any]])->dict[str,Any]:
    if not isfinite(entry) or entry<=0 or direction not in ("LONG","SHORT"):
        raise ValueError("invalid entry or direction")
    if not contexts or any(not c.get("complete") for c in contexts.values()):
        return {"status":"UNKNOWN","price":None,"distance_pct":None,
                "source":None,"mode":"SHADOW_ONLY"}
    candidates=[]
    for tf,ctx in contexts.items():
        key="pivots_high" if direction=="LONG" else "pivots_low"
        for p in ctx.get(key,()):
            try:
                px=float(p["price"])
                if not isfinite(px) or px<=0:continue
                if (direction=="LONG" and px>entry) or (direction=="SHORT" and px<entry):
                    candidates.append((abs(px-entry),tf,px))
            except (TypeError,ValueError,KeyError):
                return {"status":"UNKNOWN","price":None,"distance_pct":None,
                        "source":None,"mode":"SHADOW_ONLY"}
    if not candidates:
        return {"status":"NO_CONFIRMED_OPPOSING_LEVEL","price":None,
                "distance_pct":None,"source":None,"mode":"SHADOW_ONLY"}
    distance,tf,px=min(candidates)
    return {"status":"FOUND","price":px,"distance_pct":100*distance/entry,
            "source":tf,"mode":"SHADOW_ONLY"}
