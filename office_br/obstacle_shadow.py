"""Read-only structural obstacle distance for B&R shadow quality research.

Supply only previously confirmed HTF pivot prices. Never uses future levels.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence


def nearest(signal: Mapping[str, Any], levels: Sequence[Mapping[str, Any]],
            *, confirm_ts: float) -> dict[str, Any]:
    direction = str(signal["direction"]).upper()
    if direction not in ("LONG", "SHORT"):
        return {"valid": False, "reason": "DIRECTION", "mode": "SHADOW_ONLY"}
    sign = 1 if direction == "LONG" else -1
    entry, stop = float(signal["entry"]), float(signal["sl"])
    risk = abs(entry-stop)
    if risk <= 0 or sign*(entry-stop) <= 0:
        return {"valid": False, "reason": "GEOMETRY", "mode": "SHADOW_ONLY"}
    candidates = []
    for level in levels:
        # Only pivots whose confirmation timestamp is known and strictly in the past.
        if "confirmed_ts" not in level or float(level["confirmed_ts"]) > confirm_ts:
            continue
        price = float(level["price"])
        if sign*(price-entry) > 0:
            candidates.append((sign*(price-entry), price, str(level.get("tf", "unknown"))))
    if not candidates:
        return {"valid": True, "obstacle_r": None, "reason": "NO_CONFIRMED_AHEAD_LEVEL",
                "mode": "SHADOW_ONLY"}
    distance, price, tf = min(candidates)
    return {"valid": True, "obstacle_r": round(distance/risk, 4),
            "obstacle_price": price, "obstacle_tf": tf,
            "mode": "SHADOW_ONLY", "source": "OUR_IMPLEMENTATION"}
