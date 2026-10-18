"""Research-only B&R TP3 reachability diagnostics.

Exploratory thresholds came from in-sample paper outcomes; NOT production gates.
Do not claim the observed subgroup rate is predictive.
"""
from __future__ import annotations
from typing import Any, Mapping

EXPLORATORY_SYMBOLS = frozenset((
    "ONDOUSDT", "AVAXUSDT", "ADAUSDT", "NEARUSDT",
    "TIAUSDT", "ETHUSDT", "SEIUSDT",
))


def evaluate(signal: Mapping[str, Any]) -> dict[str, Any]:
    direction = str(signal["direction"]).upper()
    if direction not in ("LONG", "SHORT"):
        return {"valid": False, "reason": "DIRECTION", "mode": "SHADOW_ONLY"}
    sign = 1 if direction == "LONG" else -1
    entry, stop = float(signal["entry"]), float(signal["sl"])
    targets = [float(x["p"]) for x in signal["targets"]]
    if not targets or sign * (entry - stop) <= 0 or any(sign * (t-entry) <= 0 for t in targets):
        return {"valid": False, "reason": "GEOMETRY", "mode": "SHADOW_ONLY"}
    risk = abs(entry-stop)
    tp3_r = abs(targets[2]-entry)/risk if len(targets)>=3 else None
    if tp3_r is None:
        return {"valid": False, "reason": "MISSING_TP3", "mode": "SHADOW_ONLY"}
    return {"valid": True, "tp3_r": round(tp3_r, 4),
            "exploratory_shortlist": str(signal["symbol"]).upper() in EXPLORATORY_SYMBOLS and tp3_r < 1.5,
            "mode": "SHADOW_ONLY", "threshold_source": "IN_SAMPLE_EXPLORATORY",
            "live_gate": False}
