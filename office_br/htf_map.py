"""Read-only causal D1/H4/H1 B&R map; never gates orders or Office2."""
from __future__ import annotations
from datetime import datetime
from math import isfinite
from office_br.htf_shadow import classify
from office_br.htf_liquidity_shadow import levels
from office_br.htf_obstacle_shadow import obstacle

SECONDS = {"1d": 86400, "4h": 14400, "1h": 3600}

def _epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()

def build(symbol, confirm_ts, fetch, *, lookback=20, limit=120):
    """Never use a candle whose CLOSE is after confirm_ts, including HTF pivots."""
    frames, contexts, health = {}, {}, {}
    for tf, seconds in SECONDS.items():
        try:
            raw = fetch(symbol, tf, limit, closed_only=True)
            if not isinstance(raw, list):
                raise ValueError("missing candles")
            selected = []
            for row in raw:
                opened = _epoch(row["ts"])
                high, low, close = (float(row[k]) for k in ("high", "low", "close"))
                if not all(isfinite(x) for x in (opened, high, low, close)) or not (0 < low <= close <= high):
                    raise ValueError("invalid OHLC")
                if opened + seconds <= confirm_ts:
                    selected.append({"ts": opened, "high": high, "low": low, "close": close})
            selected.sort(key=lambda b: b["ts"])
            if len(selected) < lookback + 1 or confirm_ts - (selected[-1]["ts"] + seconds) >= seconds:
                raise ValueError("incomplete as-of history")
            frames[tf] = selected
            contexts[tf] = levels(selected, timeframe=tf, asof_ts=confirm_ts)
            health[tf] = "OK" if contexts[tf].get("complete") else "INCOMPLETE_LEVELS"
        except (KeyError, ValueError, TypeError, OverflowError):
            frames[tf] = []
            contexts[tf] = {"complete": False}
            health[tf] = "UNKNOWN"
    trend = classify(frames, confirm_ts=confirm_ts, lookback=lookback)
    if any(v != "OK" for v in health.values()):
        trend["direction"] = "UNKNOWN"
    return {"symbol": symbol, "confirm_ts": confirm_ts, "trend": trend,
            "liquidity": contexts, "health": health, "mode": "SHADOW_ONLY"}

def scenario(market_map, entry):
    """Research scenarios, not recommendations. No unknown map -> no directional claim."""
    direction = market_map["trend"]["direction"]
    if direction not in ("LONG", "SHORT"):
        return {"scenario": "NEUTRAL", "reason": "UNKNOWN_OR_MIXED_HTF", "obstacle": None}
    result = obstacle(float(entry), direction, market_map["liquidity"])
    if result["status"] != "FOUND":
        return {"scenario": "NEUTRAL", "reason": result["status"], "obstacle": result}
    return {"scenario": direction, "reason": "HTF_ALIGNMENT_RESEARCH_ONLY",
            "obstacle": result}
