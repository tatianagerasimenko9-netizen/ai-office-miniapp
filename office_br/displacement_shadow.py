"""Causal B&R intraday displacement and simple close-break structure classification.

Research labels, not verified ICT author rules. Uses only closed bars through
the evaluation index. Never places orders or modifies Office2.
"""
from __future__ import annotations
from typing import Any,Mapping,Sequence

def evaluate(bars:Sequence[Mapping[str,Any]], *, upto:int, atr_n:int=14,
             body_atr_threshold:float=1.0,close_fraction_threshold:float=0.75)->dict[str,Any]:
    if atr_n<2 or upto<atr_n or upto>=len(bars):
        raise ValueError("insufficient closed bars")
    b=bars[:upto+1]
    def tr(i:int)->float:
        hi,lo=float(b[i]["high"]),float(b[i]["low"])
        pc=float(b[i-1]["close"])
        return max(hi-lo,abs(hi-pc),abs(lo-pc))
    # Pre-event ATR: do not let the event candle inflate its own baseline.
    atr=sum(tr(i) for i in range(upto-atr_n,upto))/atr_n
    if atr<=0:raise ValueError("nonpositive ATR")
    cur=b[upto]
    op,cl,hi,lo=(float(cur[k]) for k in ("open","close","high","low"))
    if hi<=lo or not lo<=min(op,cl)<=max(op,cl)<=hi:
        raise ValueError("invalid OHLC")
    direction="LONG" if cl>op else "SHORT" if cl<op else "NEUTRAL"
    body=abs(cl-op)
    close_fraction=((cl-lo)/(hi-lo) if direction=="LONG" else
                    (hi-cl)/(hi-lo) if direction=="SHORT" else None)
    strong=(direction!="NEUTRAL" and body/atr>=body_atr_threshold and
            close_fraction>=close_fraction_threshold)
    return {"direction":direction,"body_atr":round(body/atr,6),
            "close_fraction":round(close_fraction,6) if close_fraction is not None else None,
            "displacement_candidate":strong,
            "thresholds":{"body_atr":body_atr_threshold,
                          "close_fraction":close_fraction_threshold},
            "source":"RESEARCH_HYPOTHESIS","mode":"SHADOW_ONLY"}
