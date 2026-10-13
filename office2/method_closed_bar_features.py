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
    # Closed-body candlestick patterns: strict engulfing or inside-body harami.
    old_lo = min(previous["open"], previous["close"])
    old_hi = max(previous["open"], previous["close"])
    new_lo = min(current["open"], current["close"])
    new_hi = max(current["open"], current["close"])
    opposite = ((previous["close"] > previous["open"]) !=
                (current["close"] > current["open"]))
    if opposite and new_lo < old_lo and new_hi > old_hi:
        evidence["O-CANDLE-PATTERNS"] = {
            "pattern_name": "ENGULFING", "closed_bar_confirmed": True}
    elif opposite and new_lo > old_lo and new_hi < old_hi:
        evidence["O-CANDLE-PATTERNS"] = {
            "pattern_name": "HARAMI", "closed_bar_confirmed": True}
    if len(past) >= 8:
        tail = past[-8:]
        rising = tail[-3]["low"] < tail[-2]["low"] < tail[-1]["low"]
        earlier_width = max(x["high"] for x in tail[:4]) - min(x["low"] for x in tail[:4])
        recent_width = max(x["high"] for x in tail[4:]) - min(x["low"] for x in tail[4:])
        contracting = recent_width < earlier_width
        tested = current["high"] >= max(x["high"] for x in tail)
        evidence["G-PRESS"] = {"higher_lows": rising, "level_tested": tested, "pullbacks_shrinking": contracting}
        evidence["D-PRESSURE"] = {"rising_lows": rising, "shrinking_pullbacks": contracting, "near_level": tested}
    if len(past) >= 8:
        recent = past[-8:]
        ceiling = max(x["high"] for x in recent[:5])
        floor = min(x["low"] for x in recent[:5])
        held = sum(1 for x in recent[5:] if floor <= x["close"] <= ceiling)
        evidence["G-LVL-CONSOLIDATION"] = {
            "bars_held": held, "level_broken": not (floor <= current["close"] <= ceiling)}
        inside = 0
        for x in reversed(recent[5:]):
            if x["high"] <= ceiling and x["low"] >= floor:
                inside += 1
            else:
                break
        evidence["G-FB-COMPLEX"] = {"inside_bars": inside}
    evidence["G-LVL-LIMIT"] = {"touches": sum(x["high"] >= max(y["high"] for y in past[:max(1, len(past)-3)]) for x in past[-3:]), "broken": current["close"] > max(x["high"] for x in past)}
    prior_resistance = max(x["high"] for x in past)
    tested = current["high"] >= prior_resistance
    rejected = tested and current["close"] < prior_resistance
    evidence["G-BOUNCE"] = {"level_tested": tested, "rejection_confirmed": rejected}
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
