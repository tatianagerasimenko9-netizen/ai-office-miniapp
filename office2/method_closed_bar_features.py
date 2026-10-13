"""Causal OHLCV observations for research-only Office methodology replay."""
from math import isfinite


def from_closed_bars(bars, cutoff):
    """Compute evidence from bars through cutoff inclusive; caller guarantees closure."""
    if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff < 2 or cutoff >= len(bars):
        return {}
    sample = []
    for source in bars[:cutoff + 1]:
        try:
            bar = {key: float(source[key]) for key in ("open", "high", "low", "close", "volume")}
        except (KeyError, TypeError, ValueError, OverflowError):
            return {}
        if not all(isfinite(x) for x in bar.values()):
            return {}
        if bar["high"] <= bar["low"] or not bar["low"] <= bar["open"] <= bar["high"] or not bar["low"] <= bar["close"] <= bar["high"] or bar["volume"] < 0:
            return {}
        sample.append(bar)
    current = sample[-1]
    previous = sample[-2]
    past = sample[:-1]
    span = current["high"] - current["low"]
    avg_range = sum(x["high"] - x["low"] for x in past) / len(past)
    avg_volume = sum(x["volume"] for x in past) / len(past)
    evidence = {
        "D-CANDLE-STRENGTH": {k: current[k] for k in ("open", "high", "low", "close")},
        "S-KAVYA-CONCEPTS": {"body_size": abs(current["close"] - current["open"]),
                             "bar_range": span, "close": current["close"],
                             "high": current["high"], "low": current["low"]},
    }
    # The middle candle is a confirmed three-bar pivot only once the right
    # candle has closed. This never uses a future bar beyond cutoff.
    left, center, right = sample[-3:]
    evidence["S-SWING3"] = {
        "left_high": left["high"], "center_high": center["high"],
        "right_high": right["high"], "left_low": left["low"],
        "center_low": center["low"], "right_low": right["low"]}
    # Historical range boundaries exclude the candle under evaluation.
    if len(past) >= 5:
        lookback = past[-20:]
        evidence["S-RANGE"] = {"range_low": min(x["low"] for x in lookback),
                               "range_high": max(x["high"] for x in lookback),
                               "close": current["close"]}
    evidence["S-FVG"] = {"first_high": left["high"], "first_low": left["low"],
                         "third_high": right["high"], "third_low": right["low"]}
    if len(past) >= 5:
        older, newer = past[-4:-2], past[-2:]
        evidence["S-STRUCTURE"] = {
            "previous_high": max(x["high"] for x in older),
            "current_high": max(x["high"] for x in newer),
            "previous_low": min(x["low"] for x in older),
            "current_low": min(x["low"] for x in newer)}
        evidence["D-FIB-LEVELS"] = {
            "swing_low": min(x["low"] for x in past[-20:]),
            "swing_high": max(x["high"] for x in past[-20:])}
    if len(past) >= 5:
        ceiling = max(x["high"] for x in past[-20:])
        floor = min(x["low"] for x in past[-20:])
        side = ("LONG" if current["low"] < floor < current["close"]
                else "SHORT" if current["high"] > ceiling > current["close"]
                else None)
        if side:
            level = floor if side == "LONG" else ceiling
            evidence["G-FB-1BAR"] = {
                "swept_level": True, "returned_inside": True, "bars": 1}
            evidence["S-LIQUIDITY-RAID"] = {
                "swept_level": level, "close": current["close"], "direction": side}
            evidence["D-FALSE-BREAK"] = {
                "level": level, "high": current["high"], "low": current["low"],
                "close": current["close"], "direction": side}
            evidence["G-FALSE-BREAK-DEF"] = evidence["D-FALSE-BREAK"].copy()
    if len(past) >= 6:
        earlier = past[:-1]
        upper = max(x["high"] for x in earlier[-20:])
        lower = min(x["low"] for x in earlier[-20:])
        # First bar closes beyond the previous range; second closes back inside.
        rejected = ((previous["close"] > upper and current["close"] < upper)
                    or (previous["close"] < lower and current["close"] > lower))
        evidence["G-FB-2BAR"] = {
            "first_closed_beyond": previous["close"] > upper or previous["close"] < lower,
            "second_rejected": rejected, "bars": 2}
    if avg_volume > 0:
        evidence["D-VOLUME-PRICE"] = {"current_volume": current["volume"],
                                      "average_volume": avg_volume,
                                      "price_change": current["close"] - previous["close"]}
    if avg_range > 0:
        evidence["G-PROGNOSTIC"] = {"bar_range": span, "average_range": avg_range,
                                    "close": current["close"], "high": current["high"], "low": current["low"]}
        for rule in ("D-PARANORMAL-IMPULSE", "G-LVL-PARANORMAL"):
            evidence[rule] = {"range": span, "average_range": avg_range}
    return evidence


def daily_atr_observation(bars, cutoff):
    """Previous 3-5 closed daily true ranges, excluding current day."""
    if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff < 3 or cutoff >= len(bars):
        return {}
    previous = bars[max(0, cutoff - 5):cutoff]
    ranges = []
    for bar in previous:
        try:
            high, low = float(bar["high"]), float(bar["low"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return {}
        if not isfinite(high) or not isfinite(low) or high <= low:
            return {}
        ranges.append(high - low)
    return {"G-ATR-CALC": {"previous_ranges": ranges}}
