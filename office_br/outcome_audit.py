"""Independent, fail-closed B&R event ledger audit.

Validates paper touch ordering and geometry. Does not assert exchange fills.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def audit(signal: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    issues: list[str] = []
    direction = str(signal["direction"]).upper()
    entry, stop = float(signal["entry"]), float(signal["sl"])
    sg = 1 if direction == "LONG" else -1
    if direction not in ("LONG", "SHORT") or sg * (entry - stop) <= 0:
        issues.append("INVALID_STOP_GEOMETRY")
    targets = signal["targets"]
    for i, t in enumerate(targets[:3]):
        p = float(t["p"])
        if sg * (p - entry) <= 0:
            issues.append(f"INVALID_TP{i+1}_GEOMETRY")
        if i and sg * (p - float(targets[i-1]["p"])) <= 0:
            issues.append("UNSORTED_TARGETS")
    by_level: dict[str, Mapping[str, Any]] = {}
    for e in events:
        level = str(e["level"])
        if level in by_level:
            issues.append(f"DUPLICATE_{level}")
        by_level[level] = e
    if "ENTRY" not in by_level:
        if any(x in by_level for x in ("TP1", "TP2", "TP3", "SL")):
            issues.append("OUTCOME_WITHOUT_ENTRY")
    else:
        entered = float(by_level["ENTRY"]["touched_ts"])
        for level in ("TP1", "TP2", "TP3", "SL"):
            if level in by_level and float(by_level[level]["touched_ts"]) <= entered:
                issues.append(f"{level}_NOT_AFTER_ENTRY")
    for i in (2, 3):
        if f"TP{i}" in by_level and f"TP{i-1}" not in by_level:
            issues.append(f"TP{i}_WITHOUT_TP{i-1}")
    if "SL" in by_level and "TP3" in by_level:
        issues.append("SL_AND_TP3_TERMINAL")
    if "AMBIGUOUS" in by_level and any(x in by_level for x in ("SL", "TP1", "TP2", "TP3")):
        issues.append("AMBIGUOUS_WITH_DETERMINISTIC_OUTCOME")
    return {"valid": not issues, "issues": sorted(set(issues)), "mode": "PAPER_LEDGER_AUDIT",
            "exchange_fills_verified": False}
