"""Read-only early-mover candidate selection, not a trade signal.

Research hypotheses inspired by chart review, not claims from the video.
No future candles, no order placement, no percent-return promises.
"""
from __future__ import annotations
from typing import Any

def screen(symbol: str, bars: list[dict[str, Any]], *,
           min_bars: int = 100, volume_ratio_min: float = 1.8,
           breakout_buffer_pct: float = 0.1, max_extension_pct: float = 6.0) -> dict[str, Any]:
    """All input bars MUST be closed; caller verifies exchange timestamp/freshness."""
    base = {"symbol":symbol,"status":"REJECT","reasons":[],"mode":"RESEARCH_ONLY"}
    if len(bars) < min_bars:
        base["reasons"].append("INSUFFICIENT_HISTORY")
        return base
    try:
        b=bars[-1]
        prev=bars[-49:-1]
        highs=[float(x["high"]) for x in prev]
        lows=[float(x["low"]) for x in prev]
        vols=[float(x["volume"]) for x in prev]
        close=float(b["close"]); vol=float(b["volume"])
        if close<=0 or min(lows)<=0 or min(vols)<0 or vol<0:
            raise ValueError("invalid market values")
        level=max(highs)
        avg_vol=sum(vols[-20:])/20
        ratio=vol/avg_vol if avg_vol>0 else 0.0
        extension_pct=100*(close/level-1)
        range_pct=100*(max(highs)-min(lows))/min(lows)
        base.update({"breakout_level":level,"volume_ratio":round(ratio,3),
                     "extension_pct":round(extension_pct,3),"range_pct":round(range_pct,3)})
        if extension_pct < breakout_buffer_pct:
            base["reasons"].append("NO_CONFIRMED_BREAKOUT")
        if ratio < volume_ratio_min:
            base["reasons"].append("WEAK_RELATIVE_VOLUME")
        if extension_pct > max_extension_pct:
            base["reasons"].append("OVEREXTENDED_NO_CHASE")
        if not base["reasons"]:
            base["status"]="WATCH_RETEST"
            base["reasons"]=["BREAKOUT_AND_VOLUME_CONFIRMED_WAIT_RETEST"]
        return base
    except (ValueError,TypeError,KeyError,ZeroDivisionError,OverflowError):
        base["reasons"].append("INVALID_DATA")
        return base

def rank(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic watchlist only, no future outcomes in ranking."""
    good=[c for c in candidates if c.get("status")=="WATCH_RETEST"]
    return sorted(good,key=lambda x:(-float(x["volume_ratio"]),float(x["extension_pct"]),str(x["symbol"])))
