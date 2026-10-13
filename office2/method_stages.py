"""Assign source rules to a top-down decision pipeline.

Classification is a processing order, not an invented entry condition.
"""
from __future__ import annotations

from typing import Any, Mapping

STAGES = (
    "D1_H4_CONTEXT",
    "H1_SCENARIO",
    "M15_SETUP",
    "M5_M1_TRIGGER",
    "RISK_EXECUTION",
    "QA_RESEARCH",
)


def stage_for(rule: Mapping[str, Any]) -> str:
    rule_id = str(rule.get("rule_id", ""))
    method = str(rule.get("method", ""))
    tf = str(rule.get("context_tf", "")).upper()
    if rule_id.startswith("X-") or method in {"GERCHIK_TRAINING", "GERCHIK_SCOPE", "OFFICE_PRODUCT_QA", "OFFICE_UX_EXAMPLE"}:
        return "QA_RESEARCH"
    if method in {"GERCHIK_RISK", "GERCHIK_ATR"} or rule_id.startswith(("G-STOP", "G-RISK", "G-RR", "G-BE", "G-TP", "D-STOP", "D-ATR", "S-RISK")):
        return "RISK_EXECUTION"
    if method in {"GERCHIK_LEVELS", "GERCHIK_RANGE", "WYCKOFF"} or rule_id.startswith(("D-FIB", "D-FRACTAL", "D-HTF", "D-LEVEL-TYPES", "D-WYCKOFF", "S-STRUCTURE", "S-RANGE")):
        return "D1_H4_CONTEXT"
    if method in {"GERCHIK_FALSE_BREAK", "GERCHIK_BOUNCE", "GERCHIK_BREAKOUT", "BULKOWSKI"} or rule_id.startswith(("D-SCENARIO", "D-ELLIOTT", "S-REVERSAL", "S-PO3")):
        return "H1_SCENARIO"
    if rule_id.startswith(("D-ENTRY", "D-NO-CONFIRMATION", "G-SIGNAL-CLOSE", "S-SWING", "S-FVG", "S-OB", "S-OTE")):
        return "M5_M1_TRIGGER"
    if "D1" in tf and "M5" not in tf and "M1" not in tf:
        return "D1_H4_CONTEXT"
    return "M15_SETUP"


def staged_registry(rules: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Every rule appears exactly once; UNKNOWN is never treated as PASS."""
    groups: dict[str, list[dict[str, Any]]] = {stage: [] for stage in STAGES}
    for rule in rules:
        groups[stage_for(rule)].append({
            "rule_id": rule["rule_id"],
            "method": rule["method"],
            "status": "UNKNOWN",
            "source_class": rule.get("evidence_class", "UNKNOWN"),
            "implementation_status": rule.get("implementation_status", "UNKNOWN"),
            "missing_parameters": rule.get("missing_parameters") or [],
        })
    return groups
