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
