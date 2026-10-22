"""Conservative B&R same-idea matcher; no order execution."""
from __future__ import annotations

TERMINAL = {"SL", "TP3", "AMBIGUOUS", "TIMEOUT", "INVALIDATED", "EXPIRED_UNSENT", "DATA_GAP"}

def same_idea(old: dict, symbol: str, new: dict, now: float) -> bool:
    """Match only close price structures, direction and recent overlapping lifetimes.

    Provisional risk-relative bounds, deliberately strict to avoid hiding independent trades.
    """
    if old["symbol"] != symbol or old["direction"] != new["direction"]:
        return False
    if old["status"] in TERMINAL:
        return False
    if not 0 <= now - float(old["created_ts"]) <= 24 * 3600:
        return False
    risk_old = abs(float(old["entry"]) - float(old["sl"]))
    risk_new = abs(float(new["entry"]) - float(new["sl"]))
    if min(risk_old, risk_new) <= 0:
        return False
    risk = min(risk_old, risk_new)
    return (abs(float(old["entry"]) - float(new["entry"])) <= .35 * risk
            and abs(float(old["sl"]) - float(new["sl"])) <= .35 * risk
            and abs(float(old["level"]) - float(new["level"])) <= .35 * risk)
