"""Read-only B&R candidate quality diagnostics. All thresholds are operational HYPOTHESES.

This module does NOT gate production signals and never submits orders.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def evaluate(candidate: Mapping[str, Any], *, htf_direction: str | None = None,
             obstacle_r: float | None = None, spread_bps: float | None = None,
             sibling_levels: Sequence[float] = (), max_spread_bps: float = 12.0,
             min_obstacle_r: float = 1.5, near_level_r: float = 0.5) -> dict[str, Any]:
    """Produce transparent shadow diagnostics; no unsupported 'author rule' claims."""
    entry = float(candidate["entry"])
    sl = float(candidate["sl"])
    risk = abs(entry - sl)
    if risk <= 0 or entry <= 0:
        return {"eligible_shadow": False, "reasons": ["INVALID_RISK"], "source": "OUR_IMPLEMENTATION"}
    direction = str(candidate["direction"]).upper()
    reasons: list[str] = []
    unknown: list[str] = []
    if htf_direction is None:
        unknown.append("HTF_DIRECTION_UNAVAILABLE")
    elif htf_direction.upper() not in ("LONG", "SHORT", "RANGE"):
        unknown.append("HTF_DIRECTION_UNKNOWN")
    elif htf_direction.upper() == "RANGE":
        reasons.append("RANGE_BREAKOUT_UNCONFIRMED")
    elif htf_direction.upper() != direction:
        reasons.append("COUNTERTREND")
    if obstacle_r is None:
        unknown.append("OBSTACLE_DISTANCE_UNAVAILABLE")
    elif obstacle_r < min_obstacle_r:
        reasons.append("NEAR_HTF_OBSTACLE")
    if spread_bps is None:
        unknown.append("SPREAD_UNAVAILABLE")
    elif spread_bps > max_spread_bps:
        reasons.append("WIDE_SPREAD")
    if any(abs(entry - float(x)) <= near_level_r * risk for x in sibling_levels):
        reasons.append("OVERLAPPING_LEVEL")
    return {
        "eligible_shadow": not reasons and not unknown,
        "reasons": reasons,
        "unknown": unknown,
        "risk_pct": 100.0 * risk / entry,
        "source": "OUR_IMPLEMENTATION",
        "mode": "SHADOW_ONLY",
    }
