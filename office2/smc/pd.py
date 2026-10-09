"""PD Array: dealing range, Equilibrium, Premium/Discount, OTE (0,5 / 0,62 / 0,705 / 0,79) з явним походженням якорів (S13). Застарілі якорі (старі swing) не вважаються актуальним range."""
from __future__ import annotations

from typing import Any, Dict, Optional

OTE_LEVELS = (0.5, 0.62, 0.705, 0.79)
MAX_ANCHOR_AGE_BARS = 400


def dealing_range(lo: float, hi: float, lo_i: int, hi_i: int, now_i: int, tf: str = "m15", max_age: int = MAX_ANCHOR_AGE_BARS) -> Optional[Dict[str, Any]]:
    if hi <= lo:
        return None
    age = now_i - min(lo_i, hi_i)
    return {"low": float(lo), "high": float(hi), "eq": float((lo + hi) / 2.0), "low_i": int(lo_i), "high_i": int(hi_i), "tf": tf, "age_bars": int(age), "stale": bool(age > max_age),
            "provenance": f"low@{lo_i} high@{hi_i} ({tf})"}


def zone_of(price: float, dr: Dict[str, Any]) -> str:
    if price > dr["eq"]:
        return "PREMIUM"
    if price < dr["eq"]:
        return "DISCOUNT"
    return "EQ"


def ote(dr: Dict[str, Any], direction: str) -> Dict[str, Any]:
    """OTE для входу ПО напрямку тренду після корекції: LONG — відкат від high вниз (зона 0,62–0,79, найкраща 0,705); SHORT — дзеркально."""
    leg = dr["high"] - dr["low"]
    if direction == "LONG":
        px = {str(r): dr["high"] - r * leg for r in OTE_LEVELS}
        zone = [dr["high"] - 0.79 * leg, dr["high"] - 0.62 * leg]
        sweet = dr["high"] - 0.705 * leg
    else:
        px = {str(r): dr["low"] + r * leg for r in OTE_LEVELS}
        zone = [dr["low"] + 0.62 * leg, dr["low"] + 0.79 * leg]
        sweet = dr["low"] + 0.705 * leg
    return {"zone": [float(min(zone)), float(max(zone))], "sweet": float(sweet), "levels": {k: float(v) for k, v in px.items()}, "stale_anchor": bool(dr["stale"]),
            "note": "OTE без тригера ≠ READY; ціна може не дійти до зони"}
