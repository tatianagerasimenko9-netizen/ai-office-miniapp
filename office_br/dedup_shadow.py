"""B&R duplicate-idea detector, shadow-only.

Suppressing real alerts requires separate out-of-sample validation.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def duplicate_idea(candidate: Mapping[str, Any], recent: Sequence[Mapping[str, Any]],
                   *, window_seconds: int = 3600, level_atr: float = 0.5) -> dict[str, Any]:
    """Compare same-symbol, same-direction, nearby levels in a rolling time window.

    Uses confirmation time and ATR from the candidate, not future candles.
    """
    atr = float(candidate.get("atr") or 0)
    now = float(candidate["confirm_ts"])
    level = float(candidate["level"])
    if atr <= 0 or window_seconds <= 0 or level_atr < 0:
        return {"duplicate": False, "valid": False, "reason": "MISSING_OR_INVALID_INPUT",
                "mode": "SHADOW_ONLY"}
    matches = []
    for prior in recent:
        if str(prior["symbol"]).upper() != str(candidate["symbol"]).upper():
            continue
        if str(prior["direction"]).upper() != str(candidate["direction"]).upper():
            continue
        dt = now - float(prior["confirm_ts"])
        if not 0 < dt <= window_seconds:
            continue
        if abs(level - float(prior["level"])) <= level_atr * atr:
            matches.append(str(prior.get("sig_id", "unknown")))
    return {"duplicate": bool(matches), "valid": True, "matched_ids": matches,
            "reason": "SAME_IDEA_NEAR_LEVEL" if matches else "DISTINCT",
            "mode": "SHADOW_ONLY", "thresholds_source": "OUR_IMPLEMENTATION"}
