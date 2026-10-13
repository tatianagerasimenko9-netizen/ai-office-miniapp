"""Dependency-first processing order for the 82-rule methodology registry.

A rule can contribute evidence without vetoing a trade. The phases represent
system architecture, not a claim of author-provided numerical thresholds.
"""
from __future__ import annotations

PHASES = (
    ("01_DATA", ("D-SESSIONS-NEWS", "S-SESSIONS", "G-ATR-CALC", "D-ATR-LIMITS", "G-ATR-DAYUSED")),
    ("02_HTF_STRUCTURE", ("D-FRACTAL-TF", "S-SWING3", "S-STRUCTURE", "S-RANGE", "G-CHANNEL", "D-ELLIOTT-RULES", "D-FIB-LEVELS", "D-FIB-REACTION-NOT-LIMITS", "D-HTF-LTF-CONFIRM")),
    ("03_LEVELS_LIQUIDITY", ("G-LVL-CONSTRUCTION", "G-LVL-LIMIT", "G-LVL-PARANORMAL", "G-LVL-TRENDBREAK", "G-LVL-MIRROR", "G-LVL-CONSOLIDATION", "G-LVL-FLOATING", "G-LVL-CONFIRM-SIGNS", "D-LEVEL-TYPES", "D-LEVEL-STICKING", "S-LIQUIDITY-RAID", "S-OB", "S-FVG", "S-BLOCKS-OTHER", "S-OTE-PD")),
    ("04_MARKET_BEHAVIOR", ("D-WYCKOFF-CONTEXT", "S-PO3", "D-VOLUME-PRICE", "D-CANDLE-STRENGTH", "D-PARANORMAL-IMPULSE", "D-POST-IMPULSE-BASE", "G-IMPULSE", "G-PRESS", "D-PRESSURE", "G-PROGNOSTIC", "G-CRYPTO-SCORE", "S-KAVYA-CONCEPTS")),
    ("05_SCENARIO", ("S-REVERSAL-CONT", "G-FALSE-BREAK-DEF", "G-FB-1BAR", "G-FB-2BAR", "G-FB-COMPLEX", "G-FB-DEPTH", "D-FALSE-BREAK", "G-BOUNCE", "G-BREAKOUT", "D-HTF-STRONG-CANDLE-PULLBACK", "G-FIGURES-UNMAPPED", "X-NOT-SPECIFIED-BULKOWSKI", "X-NOT-SPECIFIED-WYCKOFF-NUMERIC", "D-SCENARIO-CHECKLIST")),
    ("06_ENTRY", ("G-SIGNAL-CLOSE", "D-ENTRY-CLOSE-WITHIN-HALF-ATR", "D-REACTION-AFTER-RETURN", "D-NO-CONFIRMATION-NO-TRADE", "G-NO-CHASE", "O-CANDLE-PATTERNS", "X-NOT-SPECIFIED-DARIA-LTF-ENTRY-TP")),
    ("07_RISK", ("G-STOP-CALC", "G-STOP-TECH", "G-STOP-CRYPTO", "G-STOP-ATR", "G-STOP-CRYPTO-TECHNICAL", "D-STOP-STRUCTURE", "D-STOP-ATR-MARGIN", "G-LUFT", "G-LUFT-FILL", "G-RR-MIN3", "G-RISK-TRADE", "G-RISK-DAY", "S-RISK")),
    ("08_MANAGEMENT", ("G-BE", "G-BE-2R", "G-TP-TRAIL")),
    ("09_VALIDATION_UX", ("G-TRIAL-100", "G-INDICATORS-NOT-USED", "X-UX-CRB-BTW", "X-QA-RUNE")),
)


def validate_sequence(rules):
    registered = [r["rule_id"] for r in rules]
    ordered = [rule_id for _, ids in PHASES for rule_id in ids]
    missing = sorted(set(registered) - set(ordered))
    extra = sorted(set(ordered) - set(registered))
    duplicates = sorted({x for x in ordered if ordered.count(x) > 1})
    if missing or extra or duplicates or len(ordered) != len(registered):
        raise ValueError({"missing": missing, "extra": extra, "duplicates": duplicates})
    return True


def decision_trace(rules):
    validate_sequence(rules)
    lookup = {r["rule_id"]: r for r in rules}
    return [{"phase": phase, "rules": [
        {"rule_id": rid, "status": "UNKNOWN", "implementation_status": lookup[rid].get("implementation_status", "UNKNOWN")}
        for rid in ids
    ]} for phase, ids in PHASES]


def evaluate_chain(rules, evidence_by_rule=None):
    """Run the complete ordered registry with explicit unknown evidence."""
    validate_sequence(rules)
    from office2.method_predicates import evaluate
    evidence_by_rule = evidence_by_rule or {}
    registry = {r["rule_id"]: r for r in rules}
    phases = []
    counts = {"PASS": 0, "FAIL": 0, "UNKNOWN": 0, "NOT_APPLICABLE": 0}
    for phase, ids in PHASES:
        items = []
        for rid in ids:
            inputs = evidence_by_rule.get(rid, {})
            result = evaluate(rid, inputs)
            state = result["status"]
            counts[state] += 1
            items.append({"rule_id": rid, "status": state,
                          "source_class": registry[rid].get("evidence_class"),
                          "details": result})
        phases.append({"phase": phase, "rules": items})
    return {"phases": phases, "counts": counts, "evaluated": sum(counts.values()),
            "role": "SHADOW", "decision": "UNDETERMINED"}
