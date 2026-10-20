"""Causal, closed-bar B&R shadow BOS/CHOCH labeling.

A pivot is eligible only after its right-hand confirmation bars close.
Direction of the last confirmed break determines BOS (continuation) vs
CHOCH (reversal). Initial break is UNCLASSIFIED, never guessed.
Research labels only; not author-certified rules or a live signal gate.
"""
from __future__ import annotations
from typing import Any,Mapping,Sequence

def classify(bars:Sequence[Mapping[str,Any]],*,upto:int,pivot_k:int=2)->dict[str,Any]:
    if pivot_k<1 or upto<2*pivot_k+1 or upto>=len(bars):
        raise ValueError("insufficient closed bars")
    highs=[float(b["high"]) for b in bars[:upto+1]]
    lows=[float(b["low"]) for b in bars[:upto+1]]
    closes=[float(b["close"]) for b in bars[:upto+1]]
    pivots=[]
    for i in range(pivot_k,upto-pivot_k+1):
        if all(highs[i]>highs[i-j] and highs[i]>=highs[i+j] for j in range(1,pivot_k+1)):
            pivots.append({"index":i,"confirmed":i+pivot_k,"side":"H","price":highs[i]})
        if all(lows[i]<lows[i-j] and lows[i]<=lows[i+j] for j in range(1,pivot_k+1)):
            pivots.append({"index":i,"confirmed":i+pivot_k,"side":"L","price":lows[i]})
    broken=set()
    prior_direction=None
    events=[]
    for t in range(2*pivot_k+1,upto+1):
        for side,sign,direction in (("H",1,"LONG"),("L",-1,"SHORT")):
            candidates=[p for p in pivots if p["side"]==side and p["confirmed"]<t
                        and p["index"] not in broken]
            if not candidates:continue
            p=candidates[-1]
            if sign*(closes[t]-p["price"])>0 and sign*(closes[t-1]-p["price"])<=0:
                label=("UNCLASSIFIED" if prior_direction is None else
                       "BOS" if prior_direction==direction else "CHOCH")
                events.append({"index":t,"pivot_index":p["index"],"direction":direction,
                               "label":label,"level":p["price"]})
                prior_direction=direction
                broken.add(p["index"])
    return {"events":events,"trend_after":prior_direction,
            "mode":"SHADOW_ONLY","pivot_k":pivot_k,
            "method":"CONFIRMED_PIVOT_CLOSE_BREAK_RESEARCH"}
