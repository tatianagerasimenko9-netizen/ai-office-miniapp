"""Provenance-aware source-rule evaluation for AI Office.

Read-only advisory evidence: NEVER changes READY, live orders, or risk limits.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "docs" / "sources" / "evidence.jsonl"
VALID_ROLES = frozenset({"GATE", "EVIDENCE", "SHADOW", "DISPLAY"})
VALID_STATES = frozenset({"PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"})


def load_rules(path: Path = DEFAULT_REGISTRY) -> list[dict[str, Any]]:
    """Validate complete rule registry; fail loudly on missing/duplicate rules."""
    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as stream:
        for line_no, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                rule = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
            if not isinstance(rule, dict) or not isinstance(rule.get("rule_id"), str) or not rule["rule_id"].strip():
                raise ValueError(f"{path}:{line_no}: missing rule_id")
            if rule["rule_id"] in seen:
                raise ValueError(f"{path}:{line_no}: duplicate {rule['rule_id']}")
            if not rule.get("method") or not isinstance(rule.get("source_files"), list):
                raise ValueError(f"{path}:{line_no}: missing method or source_files")
            seen.add(rule["rule_id"])
            rules.append(rule)
    if not rules:
        raise ValueError(f"{path}: empty registry")
    return rules


def rule_coverage(rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Inventory of documented roles, not a claim of executable coverage."""
    return {
        "total": len(rules),
        "by_method": dict(sorted(Counter(str(r.get("method")) for r in rules).items())),
        "by_implementation_status": dict(sorted(Counter(str(r.get("implementation_status", "UNKNOWN")) for r in rules).items())),
        "without_code_refs": sorted(r["rule_id"] for r in rules if not r.get("code_refs")),
        "without_source_files": sorted(r["rule_id"] for r in rules if not r.get("source_files")),
    }


def advisory_snapshot(
    rules: list[dict[str, Any]],
    *,
    symbol: str,
    asof_utc: str,
    timeframes: Mapping[str, Any] | None = None,
    evidence_by_rule: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build transparent evidence without pretending unknown rules have passed.

    evidence_by_rule is provided by tested, external evaluators; this module
    does not derive price signals from text or promote shadow to GATE.
    """
    evidence_by_rule = evidence_by_rule or {}
    registered = {r["rule_id"] for r in rules}
    unknown_ids = set(evidence_by_rule) - registered
    if unknown_ids:
        raise ValueError(f"unregistered rule IDs: {sorted(unknown_ids)}")
    evaluations = []
    for rule in rules:
        rule_id = rule["rule_id"]
        supplied = evidence_by_rule.get(rule_id, {})
        state = supplied.get("status", "UNKNOWN")
        if state not in VALID_STATES:
            raise ValueError(f"{rule_id}: invalid status {state!r}")
        # Never accept an external GATE role as a silent policy change.
        evaluations.append({
            "rule_id": rule_id,
            "method": rule["method"],
            "status": state,
            "decision_role": "SHADOW",
            "source_class": rule.get("evidence_class", "UNKNOWN"),
            "source_files": rule["source_files"],
            "evidence": list(supplied.get("evidence") or []),
            "missing_inputs": list(rule.get("missing_parameters") or []) if state == "UNKNOWN" else [],
        })
    tfs = timeframes or {}
    return {
        "schema_version": "method_decision_v1",
        "symbol": symbol,
        "asof_utc": asof_utc,
        "timeframes": {tf: tfs.get(tf) for tf in ("D1", "H4", "H1", "M15", "M5", "M1")},
        "rule_evaluations": evaluations,
        "decision_role": "SHADOW",
        "decision": "NOT_EVALUATED",
        "reason": "Source registry evidence only; existing Brain controls READY.",
    }


def compact_method_trace(thesis: Mapping[str, Any], now: float) -> dict[str, Any]:
    """Small provenance-aware reasoning trace for a frozen READY.

    Source-method rules are indexed by ID; never serialize the entire registry
    into each signal, and never silently promote unverified rules into gates.
    """
    from datetime import datetime, timezone

    rules = load_rules()
    by_id = {r["rule_id"]: r for r in rules}
    observed = []
    for group, ids, fact in (
        ("topdown", ("D-HTF-LTF-CONFIRM", "G-LEVEL-HTF-FIRST"), thesis.get("map")),
        ("level", ("G-LVL-FLOATING", "G-LUFT"), thesis.get("entry_zone") or thesis.get("zone")),
        ("structure", ("D-NO-CONFIRMATION-NO-TRADE",), thesis.get("sequence")),
        ("ltf", ("X-NOT-SPECIFIED-DARIA-LTF-ENTRY-TP",), (thesis.get("topdown") or {}).get("ltf")),
    ):
        for rule_id in ids:
            if rule_id not in by_id:
                continue
            observed.append({
                "rule_id": rule_id,
                "group": group,
                "status": "OBSERVED_UNVERIFIED" if fact is not None else "UNKNOWN",
                "role": "SHADOW",
                "source_class": by_id[rule_id].get("evidence_class", "UNKNOWN"),
            })
    return {
        "schema_version": "method_trace_v1",
        "asof_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "decision_role": "SHADOW",
        "registered_rule_count": len(rules),
        "evaluations": observed,
        "methodology_coverage": "PARTIAL",
        "note": "Observation is not source-rule confirmation; Brain gates unchanged.",
    }
