"""Causal OHLCV observations for research-only Office methodology replay."""
from math import isfinite


def _daily_atr(daily_ranges):
    """Mean of 3-5 previous closed daily ranges (G-ATR-CALC); None when invalid."""
    if not isinstance(daily_ranges, (list, tuple)) or not 3 <= len(daily_ranges) <= 5:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) or v <= 0
           for v in daily_ranges):
        return None
    return sum(daily_ranges) / len(daily_ranges)


def _day_range(day_bars):
    """High-low of closed bars of the current day up to cutoff; None when invalid."""
    if not isinstance(day_bars, (list, tuple)) or not day_bars:
        return None
    try:
        highs = [float(b["high"]) for b in day_bars]
        lows = [float(b["low"]) for b in day_bars]
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not all(isfinite(v) for v in highs + lows) or max(highs) <= min(lows):
        return None
    return max(highs) - min(lows)


def from_closed_bars(bars, cutoff, daily_ranges=None, day_bars=None):
    """Compute evidence from bars through cutoff inclusive; caller guarantees closure.

    Optional daily context (caller guarantees it is closed before the cutoff):
    daily_ranges = 3-5 previous closed daily high-low ranges (current day excluded);
    day_bars = closed bars of the current day up to cutoff. Rules needing them are
    simply absent (UNKNOWN downstream) when they are not supplied.
    """
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
    side = None
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
    resistance_reference = max(x["high"] for x in past[:-3]) if len(past) >= 6 else max(x["high"] for x in past)
    evidence["G-LVL-LIMIT"] = {"touches": sum(x["high"] >= resistance_reference for x in past[-3:]), "broken": current["close"] > resistance_reference}
    prior_resistance = max(x["high"] for x in past)
    tested = current["high"] >= prior_resistance
    rejected = tested and current["close"] < prior_resistance
    evidence["G-BOUNCE"] = {"level_tested": tested, "rejection_confirmed": rejected}
    wick = current["high"] - max(current["open"], current["close"])
    body = abs(current["close"] - current["open"])
    evidence["G-LVL-CONFIRM-SIGNS"] = {"touches": evidence["G-LVL-LIMIT"]["touches"], "false_break": rejected, "long_wick": wick > body}
    if len(past) >= 8:
        level = max(x["high"] for x in past[-8:-3])
        previous_break = previous["close"] > level
        retested = current["low"] <= level <= current["close"]
        evidence["G-BREAKOUT"] = {"closed_beyond": previous_break, "held_retest": retested}
        evidence["G-LVL-MIRROR"] = {"was_resistance": previous_break, "now_support": retested}
    _batch2_observations(evidence, past, current, side, daily_ranges, day_bars)
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


def _batch2_observations(evidence, past, current, side, daily_ranges, day_bars):
    """Batch 2 (7 rules). Levels are prior-bar extremes only; nothing from the future."""
    if len(past) >= 5:
        lookback = past[-20:]
        ceiling = max(x["high"] for x in lookback)
        floor = min(x["low"] for x in lookback)
        signs = evidence["G-LVL-CONFIRM-SIGNS"]
        # G-LVL-FLOATING: a level counts as fixed only once confirmation signs
        # (G-LVL-CONFIRM-SIGNS) appeared; otherwise it stays floating.
        evidence["G-LVL-FLOATING"] = {"fixed_level": bool(
            signs["touches"] >= 2 or signs["false_break"] or signs["long_wick"])}
        if side:
            level = floor if side == "LONG" else ceiling
            evidence["G-SIGNAL-CLOSE"] = {"close": current["close"], "level": level, "direction": side}
            # HYPOTHESIS: entry price = close of the signal bar (source gives no entry TF/price).
            evidence["S-OTE-PD"] = {"entry": current["close"], "range_low": floor,
                                    "range_high": ceiling, "direction": side}
    if len(past) >= 6:
        tail = past[-3:]
        up = tail[0]["low"] < tail[1]["low"] < tail[2]["low"]
        down = tail[0]["high"] > tail[1]["high"] > tail[2]["high"]
        # HYPOTHESIS: "reversal bar" = opposite-colour bar closing beyond the last
        # higher-low / lower-high; the source gives no numeric definition.
        broke = (up and current["close"] < past[-1]["low"]) or (down and current["close"] > past[-1]["high"])
        opposite = (up and current["close"] < current["open"]) or (down and current["close"] > current["open"])
        evidence["G-LVL-TRENDBREAK"] = {"trend_reversed": bool(broke), "reversal_bar_confirmed": bool(opposite)}
    atr = _daily_atr(daily_ranges)
    day_range = _day_range(day_bars)
    if atr and day_range is not None:
        evidence["G-ATR-DAYUSED"] = {"day_range": day_range, "daily_atr": atr}
    if atr and side and len(past) >= 5:
        level = evidence["G-SIGNAL-CLOSE"]["level"]
        depth = level - current["low"] if side == "LONG" else current["high"] - level
        evidence["G-FB-DEPTH"] = {"break_depth": depth, "daily_atr": atr}


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
