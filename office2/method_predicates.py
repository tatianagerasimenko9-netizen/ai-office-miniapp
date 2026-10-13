"""Deterministic, closed-bar source-rule evaluators (research/shadow only).

Inputs are explicitly supplied by a closed-candle feature builder. No future
bars, network calls, hidden default thresholds, or live trading side effects.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping


def _number(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if isfinite(value) else None


def evaluate(rule_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """PASS/FAIL/UNKNOWN with explicit required inputs.

    PASS is a condition observation, NOT a recommendation to open a position.
    """
    requirements = {
        "G-SIGNAL-CLOSE": ("close", "level", "direction"),
        "G-LVL-PARANORMAL": ("range", "average_range"),
        "G-ATR-DAYUSED": ("day_range", "daily_atr"),
        "G-RR-MIN3": ("reward", "risk"),
        "G-LVL-LIMIT": ("touches", "broken"),
    }
    if rule_id not in requirements:
        return {"status": "UNKNOWN", "reason": "No verified predicate implemented"}
    required = requirements[rule_id]
    missing = [key for key in required if data.get(key) is None]
    if missing:
        return {"status": "UNKNOWN", "missing_inputs": missing}
    if rule_id == "G-LVL-LIMIT":
        touches = _number(data, "touches")
        broken = data["broken"]
        if touches is None or not isinstance(broken, bool):
            return {"status": "UNKNOWN", "reason": "invalid touches/broken"}
        passed = touches >= 3 and not broken
    elif rule_id == "G-SIGNAL-CLOSE":
        close, level = _number(data, "close"), _number(data, "level")
        direction = data.get("direction")
        if close is None or level is None or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN", "reason": "invalid price or direction"}
        passed = close > level if direction == "LONG" else close < level
    elif rule_id == "G-LVL-PARANORMAL":
        bar_range, average = _number(data, "range"), _number(data, "average_range")
        if bar_range is None or average is None or bar_range < 0 or average <= 0:
            return {"status": "UNKNOWN", "reason": "invalid bar ranges"}
        passed = bar_range >= 2 * average
    elif rule_id == "G-ATR-DAYUSED":
        day_range, atr = _number(data, "day_range"), _number(data, "daily_atr")
        if day_range is None or atr is None or day_range < 0 or atr <= 0:
            return {"status": "UNKNOWN", "reason": "invalid daily range/ATR"}
        return {"status": "PASS", "ratio": day_range / atr, "note": "measurement only; source-specific threshold not asserted"}
    else:
        reward, risk = _number(data, "reward"), _number(data, "risk")
        if reward is None or risk is None or reward < 0 or risk <= 0:
            return {"status": "UNKNOWN", "reason": "invalid reward/risk"}
        passed = reward / risk >= 3.0
    return {"status": "PASS" if passed else "FAIL", "rule_id": rule_id}
