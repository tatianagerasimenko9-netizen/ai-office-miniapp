"""B&R #13: fail-closed LONG/SHORT/NEUTRAL scenarios for manual review.

No execution, no Office2 dependency, no change to legacy signal gates.
"""
from __future__ import annotations
from math import isfinite

def evaluate(market_map, candidate_direction, entry, sl):
    if candidate_direction not in ("LONG", "SHORT"):
        return {"scenario": "NEUTRAL", "reason": "INVALID_CANDIDATE", "mode": "SHADOW_ONLY"}
    try:
        entry, sl = float(entry), float(sl)
    except (TypeError, ValueError):
        return {"scenario": "NEUTRAL", "reason": "INVALID_PRICES", "mode": "SHADOW_ONLY"}
    if not all(isfinite(v) and v > 0 for v in (entry, sl)):
        return {"scenario": "NEUTRAL", "reason": "INVALID_PRICES", "mode": "SHADOW_ONLY"}
    if (candidate_direction == "LONG" and sl >= entry) or (candidate_direction == "SHORT" and sl <= entry):
        return {"scenario": "NEUTRAL", "reason": "INVALID_STRUCTURAL_SL", "mode": "SHADOW_ONLY"}
    if market_map.get("mode") != "SHADOW_ONLY" or any(v != "OK" for v in market_map.get("health", {}).values()) or len(market_map.get("health", {})) != 3:
        return {"scenario": "NEUTRAL", "reason": "INCOMPLETE_HTF", "mode": "SHADOW_ONLY"}
    trend = market_map.get("trend", {}).get("direction")
    if trend != candidate_direction:
        return {"scenario": "NEUTRAL", "reason": "HTF_DISAGREEMENT", "mode": "SHADOW_ONLY"}
    from office_br.htf_obstacle_shadow import obstacle
    opposing = obstacle(entry, candidate_direction, market_map.get("liquidity", {}))
    if opposing["status"] != "FOUND":
        return {"scenario": "NEUTRAL", "reason": "NO_CONFIRMED_OPPOSING_LIQUIDITY", "mode": "SHADOW_ONLY"}
    risk = abs(entry - sl)
    reward = abs(opposing["price"] - entry)
    return {"scenario": candidate_direction, "reason": "HTF_AND_STRUCTURE_RESEARCH",
            "risk": risk, "nearest_liquidity": opposing["price"],
            "gross_rr_to_obstacle": reward / risk,
            "mode": "SHADOW_ONLY"}
