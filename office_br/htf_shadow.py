"""Causal D1/H4/H1 trend classification for B&R shadow research.

Input must contain ONLY candles closed before the candidate confirmation.
A disagreement or missing timeframe is UNKNOWN, never an invented trend.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence


def _direction(bars: Sequence[Mapping[str, Any]], *, lookback: int = 20) -> str:
    if len(bars) < lookback + 1:
        return "UNKNOWN"
    closes = [float(x.get("close", 0)) for x in bars]
    if any(x <= 0 for x in closes):
        return "UNKNOWN"
    current = closes[-1]
    avg = sum(closes[-lookback:]) / lookback
    prior = sum(closes[-lookback-1:-1]) / lookback
    if current > avg and avg > prior:
        return "LONG"
    if current < avg and avg < prior:
        return "SHORT"
    return "RANGE"


def classify(timeframes: Mapping[str, Sequence[Mapping[str, Any]]],
             *, confirm_ts: float, lookback: int = 20) -> dict[str, Any]:
    directions = {}
    for tf, seconds in (("1d", 86400), ("4h", 14400), ("1h", 3600)):
        bars = timeframes.get(tf, ())
        # Bar timestamps must be OPEN times. A candle closes at open+duration.
        if not bars or any(float(b["ts"]) + seconds > confirm_ts for b in bars):
            directions[tf] = "UNKNOWN"
        else:
            directions[tf] = _direction(bars, lookback=lookback)
    vals = list(directions.values())
    if "UNKNOWN" in vals:
        combined = "UNKNOWN"
    elif len(set(vals)) == 1:
        combined = vals[0]
    else:
        combined = "MIXED"
    return {"direction": combined, "by_timeframe": directions,
            "mode": "SHADOW_ONLY", "source": "OUR_IMPLEMENTATION",
            "method": "SMA20_PRICE_AND_SLOPE_HYPOTHESIS"}
