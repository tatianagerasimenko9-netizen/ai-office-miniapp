"""B&R-only fail-closed trade geometry before a Telegram READY caption.

All prices numeric, targets in correct order, net reward to TP1 after
explicit round-trip cost must be positive. No orders or Office2 changes.
"""
from __future__ import annotations
from math import isfinite
from typing import Mapping,Any

def validate(p:Mapping[str,Any],*,round_trip_cost_pct:float)->dict[str,float]:
    if not isfinite(round_trip_cost_pct) or round_trip_cost_pct<0:
        raise ValueError("invalid cost")
    d=str(p["direction"]).upper()
    if d not in ("LONG","SHORT"):raise ValueError("direction")
    keys=("entry","sl","tp1","tp2","tp3")
    v={k:float(p[k]) for k in keys}
    if not all(isfinite(x) and x>0 for x in v.values()):
        raise ValueError("invalid price")
    e,s=v["entry"],v["sl"]
    if d=="LONG" and not (s<e<v["tp1"]<v["tp2"]<v["tp3"]):
        raise ValueError("invalid LONG geometry")
    if d=="SHORT" and not (v["tp3"]<v["tp2"]<v["tp1"]<e<s):
        raise ValueError("invalid SHORT geometry")
    risk=abs(e-s)
    cost=e*round_trip_cost_pct/100
    net_risk=risk+cost
    if net_risk<=0:raise ValueError("zero risk")
    result={"risk_pct":100*risk/e,"net_risk_pct":100*net_risk/e}
    for key in ("tp1","tp2","tp3"):
        reward=abs(v[key]-e)-cost
        result[key+"_net_r"]=reward/net_risk
        if reward<=0:raise ValueError("target inside transaction costs")
    return result
