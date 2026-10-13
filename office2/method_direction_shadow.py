"""Shadow comparison of existing Brain LONG/SHORT candidates.

Only already-computed thesis fields are used. This does not change production
decisions and must be validated by independent replay before activation.
"""
from __future__ import annotations

from typing import Any, Mapping


def compare_candidates(long_thesis: Mapping[str, Any] | None, short_thesis: Mapping[str, Any] | None) -> dict[str, Any]:
    candidates = {"LONG": long_thesis, "SHORT": short_thesis}
    stages = {"READY": 3, "WAIT": 2, "WATCH": 1, "NO_TRADE": 0}
    results = {}
    for direction, thesis in candidates.items():
        if not thesis:
            results[direction] = {"status": "ABSENT", "score": None}
            continue
        state = str(thesis.get("state") or thesis.get("status") or "UNKNOWN").upper()
        if state not in stages:
            results[direction] = {"status": state, "score": None}
            continue
        results[direction] = {"status": state, "score": stages[state]}
    available = [(d, v["score"]) for d, v in results.items() if v["score"] is not None]
    if not available:
        return {"selected": "NO_TRADE", "reason": "no evaluated thesis", "candidates": results, "role": "SHADOW"}
    top = max(score for _, score in available)
    winners = [d for d, score in available if score == top]
    selected = winners[0] if len(winners) == 1 else "CONFLICT"
    return {"selected": selected, "reason": "Brain thesis maturity only; methodology not yet validated", "candidates": results, "role": "SHADOW"}
