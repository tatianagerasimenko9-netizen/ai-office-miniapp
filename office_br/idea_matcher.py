"""Conservative B&R same-idea matcher; no order execution."""
from __future__ import annotations

TERMINAL = {"SL", "TP3", "AMBIGUOUS", "TIMEOUT", "INVALIDATED", "EXPIRED_UNSENT", "DATA_GAP"}

def same_idea(old: dict, symbol: str, new: dict, now: float) -> bool:
    """Match only close price structures, direction and recent overlapping lifetimes.

    Exact same-break / same-execution plans are duplicates even if the detector
    reports multiple nearby structural levels on one confirmation candle.
    Broader risk-relative bounds remain provisional until production replay.
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
    if (old.get("break_ts") is not None and new.get("break_ts") is not None
            and float(old["break_ts"]) == float(new["break_ts"])
            and float(old["entry"]) == float(new["entry"])
            and float(old["sl"]) == float(new["sl"])):
        return True
    risk = min(risk_old, risk_new)
    return (abs(float(old["entry"]) - float(new["entry"])) <= .35 * risk
            and abs(float(old["sl"]) - float(new["sl"])) <= .35 * risk
            and abs(float(old["level"]) - float(new["level"])) <= .35 * risk)
