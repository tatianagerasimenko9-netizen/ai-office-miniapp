"""B&R-only causal structural event metrics, SHADOW ONLY.

Uses confirmed pivots (right-hand confirmation candles already closed).
Definitions are operational research hypotheses, not claims about ICT authors.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence

def analyze(bars:Sequence[Mapping[str,Any]], *, upto:int, pivot_k:int=2)->dict[str,Any]:
    if pivot_k<1 or not (2*pivot_k<upto<len(bars)):
        raise ValueError("insufficient closed candles")
    b=bars[:upto+1]
    highs=[float(x["high"]) for x in b]
    lows=[float(x["low"]) for x in b]
    closes=[float(x["close"]) for x in b]
    pivots=[]
    for i in range(pivot_k,upto-pivot_k+1):
        if all(highs[i]>highs[i-j] and highs[i]>=highs[i+j] for j in range(1,pivot_k+1)):
            pivots.append({"i":i,"type":"H","price":highs[i],"confirmed_i":i+pivot_k})
        if all(lows[i]<lows[i-j] and lows[i]<=lows[i+j] for j in range(1,pivot_k+1)):
            pivots.append({"i":i,"type":"L","price":lows[i],"confirmed_i":i+pivot_k})
    previous=[p for p in pivots if p["confirmed_i"]<upto]
    events=[]
    for kind,sg in (("H",1),("L",-1)):
        candidates=[p for p in previous if p["type"]==kind]
        if not candidates:continue
        level=candidates[-1]["price"]
        prev,now=closes[upto-1],closes[upto]
        if sg*(now-level)>0 and sg*(prev-level)<=0:
            events.append({"type":"STRUCTURE_BREAK","direction":"LONG" if sg>0 else "SHORT",
                           "level":level,"pivot_i":candidates[-1]["i"],"confirm_i":upto})
        # Wick takes liquidity and closes back inside the pivot level.
        extreme=highs[upto] if sg>0 else lows[upto]
        if sg*(extreme-level)>0 and sg*(now-level)<0:
            events.append({"type":"LIQUIDITY_SWEEP","direction":"SHORT" if sg>0 else "LONG",
                           "level":level,"pivot_i":candidates[-1]["i"],"confirm_i":upto})
    # A 3-candle imbalance uses the CURRENT closed candle and two predecessors.
    if lows[upto]>highs[upto-2]:
        events.append({"type":"FVG","direction":"LONG","low":highs[upto-2],
                       "high":lows[upto],"confirm_i":upto})
    if highs[upto]<lows[upto-2]:
        events.append({"type":"FVG","direction":"SHORT","low":highs[upto],
                       "high":lows[upto-2],"confirm_i":upto})
    return {"events":events,"confirmed_pivots":pivots,"mode":"SHADOW_ONLY",
            "limitations":["BREAK_NOT_CLASSIFIED_BOS_VS_CHOCH","NO_OB_BREAKER_VALIDATION",
                           "NO_VOLUME_OR_DISPLACEMENT_GATE","NO_AUTHOR_RULES_VERIFIED"]}
