"""B&R shadow research: explain direction-vs-HTF regime and obstacles.

All thresholds are hypotheses. No order execution or live filtering.
"""
from __future__ import annotations
from typing import Any, Mapping


def assess(signal: Mapping[str, Any], htf: Mapping[str, Any],
           obstacle: Mapping[str, Any], *, min_clearance_r: float = 1.5) -> dict[str, Any]:
    direction = str(signal["direction"]).upper()
    trend = str(htf.get("direction", "UNKNOWN")).upper()
    if direction not in ("LONG", "SHORT"):
        return {"valid": False, "mode": "SHADOW_ONLY", "reason": "DIRECTION"}
    if trend in ("UNKNOWN", "MIXED"):
        regime = trend
    elif trend == "RANGE":
        regime = "RANGE"
    elif trend == direction:
        regime = "WITH_TREND"
    elif trend in ("LONG", "SHORT"):
        regime = "COUNTERTREND"
    else:
        regime = "UNKNOWN"
    distance = obstacle.get("obstacle_r")
    if not obstacle.get("valid", False) or distance is None:
        clearance = "UNKNOWN"
    elif float(distance) < min_clearance_r:
        clearance = "NEAR_OBSTACLE"
    else:
        clearance = "CLEAR"
    return {"valid": True, "regime": regime, "clearance": clearance,
            "candidate_for_research": regime == "WITH_TREND" and clearance == "CLEAR",
            "mode": "SHADOW_ONLY", "source": "OUR_IMPLEMENTATION",
            "live_gate": False, "threshold_source": "HYPOTHESIS"}
