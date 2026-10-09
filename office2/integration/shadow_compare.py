"""Read-only порівняння Brain, SMC і Gerchik observations.

Цей модуль не створює торгового рішення: він лише зводить уже обчислені
спостереження одного symbol/direction/decision bar і зберігає provenance.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Tuple

from office2.integration.contract import validate_observation

SUPPORT_STATES = {"CONFIRMED", "ENTRY_READY", "ACTIVE", "TP"}


def _key(obs: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(obs.get("symbol") or ""),
        str(obs.get("direction") or ""),
        str(obs.get("decision_bar_close_utc") or ""),
    )


def _alignment(by_method: Dict[str, Dict[str, Any]]) -> str:
    brain = by_method.get("BRAIN")
    brain_ready = bool(brain and brain.get("state") == "ENTRY_READY")
    shadow_support = any(
        method in by_method and by_method[method].get("state") in SUPPORT_STATES
        for method in ("SMC", "GERCHIK")
    )
    shadow_ready = bool(by_method.get("SMC") and by_method["SMC"].get("state") == "ENTRY_READY")
    if brain_ready:
        return "BRAIN_READY_SHADOW_SUPPORT" if shadow_support else "BRAIN_READY_NO_SHADOW_SUPPORT"
    if shadow_ready or shadow_support:
        return "SHADOW_ONLY"
    return "OBSERVATION_ONLY"


def compare_shadow(observations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Групує валідні observations; не повертає action/READY рекомендацію."""
    source = [deepcopy(x) for x in observations]
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    errors: List[Dict[str, Any]] = []
    for obs in source:
        violations = validate_observation(obs)
        if violations:
            errors.append({"observation_id": obs.get("observation_id"), "method": obs.get("method"), "errors": violations})
            continue
        groups.setdefault(_key(obs), []).append(obs)

    rows: List[Dict[str, Any]] = []
    for key, items in sorted(groups.items()):
        by_method: Dict[str, Dict[str, Any]] = {}
        duplicates: List[str] = []
        for obs in items:
            method = str(obs["method"])
            if method in by_method:
                duplicates.append(method)
                continue
            by_method[method] = obs
        evidence: Dict[str, List[Dict[str, Any]]] = {}
        for method, obs in by_method.items():
            for side, facts in (("for", obs.get("facts_for") or []), ("against", obs.get("facts_against") or [])):
                for fact in facts:
                    semantic = str(fact.get("semantic_group") or "other")
                    provenance = {
                        "method": method,
                        "observation_id": obs["observation_id"],
                        "source_rule_ids": list(obs.get("source_rule_ids") or []),
                        "side": side,
                        "fact": deepcopy(fact),
                    }
                    evidence.setdefault(semantic, []).append(provenance)
        unavailable = {
            method: deepcopy(obs.get("missing") or [])
            for method, obs in by_method.items()
            if obs.get("missing")
        }
        rows.append({
            "symbol": key[0],
            "direction": key[1],
            "decision_bar_close_utc": key[2],
            "methods": {method: {"state": obs["state"], "observation_id": obs["observation_id"], "version": obs["version"],
                                 "source_rule_ids": list(obs.get("source_rule_ids") or [])}
                        for method, obs in sorted(by_method.items())},
            "alignment": _alignment(by_method),
            "entry_ready_methods": sorted(method for method, obs in by_method.items() if obs["state"] == "ENTRY_READY"),
            "support_methods": sorted(method for method, obs in by_method.items() if obs["state"] in SUPPORT_STATES),
            "evidence_by_semantic_group": evidence,
            "unavailable": unavailable,
            "duplicate_methods_ignored": sorted(set(duplicates)),
            "decision": None,
            "note": "SHADOW: порівняння не змінює production READY, risk або delivery",
        })
    return {
        "readonly": True,
        "shadow": True,
        "rows": rows,
        "invalid": errors,
        "summary": {
            "observations": len(source),
            "valid": sum(len(x) for x in groups.values()),
            "invalid": len(errors),
            "groups": len(rows),
            "by_alignment": {name: sum(1 for row in rows if row["alignment"] == name)
                             for name in ("BRAIN_READY_SHADOW_SUPPORT", "BRAIN_READY_NO_SHADOW_SUPPORT", "SHADOW_ONLY", "OBSERVATION_ONLY")},
        },
    }
