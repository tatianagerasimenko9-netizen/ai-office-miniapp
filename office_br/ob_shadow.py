"""B&R-only causal order-block candidate research.

An OB *candidate* is the latest opposite-direction closed candle before a
confirmed close break with a displacement candidate. No claim of institutional
order flow, mitigation, breaker status, or tradeability is made.
"""
from __future__ import annotations
from typing import Any,Mapping,Sequence
from office_br.bos_choch_shadow import classify
from office_br.displacement_shadow import evaluate

def candidates(bars:Sequence[Mapping[str,Any]],*,upto:int,pivot_k:int=2,
               lookback:int=8)->dict[str,Any]:
    if lookback<1:raise ValueError("lookback must be positive")
    structure=classify(bars,upto=upto,pivot_k=pivot_k)
    result=[]
    for event in structure["events"]:
        i=event["index"]
        if i>upto:continue
        # An order-block hypothesis requires a strong, closed break candle.
        try: displacement=evaluate(bars,upto=i,atr_n=min(14,i))
        except ValueError:continue
        if not displacement["displacement_candidate"]:continue
        direction=event["direction"]
        opposite=[]
        for j in range(max(0,i-lookback),i):
            b=bars[j]
            op,cl=float(b["open"]),float(b["close"])
            if (direction=="LONG" and cl<op) or (direction=="SHORT" and cl>op):
                opposite.append(j)
        if not opposite:continue
        j=opposite[-1]
        ob=bars[j]
        result.append({"type":"OB_CANDIDATE","direction":direction,
                       "source_i":j,"break_i":i,"structure_label":event["label"],
                       "zone_low":float(ob["low"]),"zone_high":float(ob["high"]),
                       "break_level":event["level"],"mode":"SHADOW_ONLY"})
    return {"candidates":result,"mode":"SHADOW_ONLY",
            "limitations":["NO_MITIGATION","NO_BREAKER_CLASSIFICATION",
                           "NO_VOLUME_VALIDATION","NO_AUTHOR_RULES_VERIFIED"]}
