"""Versioned, evidence-backed market thesis contract. Read-only and fail-closed.

A thesis is an analyst hypothesis, never an order or an open position.
Unverified data cannot promote a thesis into an actionable plan.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Sequence

REGIMES = frozenset({"TREND", "RANGE", "TRANSITION", "COMPRESSION", "EXPANSION", "NEWS", "ILLIQUID", "UNKNOWN"})
STATES = frozenset({"WATCHING", "CONFIRMED", "INVALIDATED", "EXPIRED"})
REQUIRED_EVIDENCE = ("source", "observed_at", "timeframe", "fact")


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def evaluate_thesis(
    thesis: Mapping[str, Any],
    *,
    now_utc: datetime,
    max_evidence_age_seconds: int = 900,
) -> Dict[str, Any]:
    """Validate provenance, expiry and mutually exclusive thesis/position states."""
    reasons = []
    now = now_utc.astimezone(timezone.utc) if now_utc.tzinfo else None
    if now is None:
        raise ValueError("now_utc must be timezone aware")
    if str(thesis.get("regime") or "").upper() not in REGIMES - {"UNKNOWN"}:
        reasons.append("REGIME_NOT_VERIFIED")
    if str(thesis.get("state") or "").upper() not in STATES:
        reasons.append("INVALID_STATE")
    if not str(thesis.get("hypothesis") or "").strip():
        reasons.append("MISSING_HYPOTHESIS")
    if not str(thesis.get("alternative") or "").strip():
        reasons.append("MISSING_ALTERNATIVE")
    if not str(thesis.get("invalidation") or "").strip():
        reasons.append("MISSING_INVALIDATION")
    if thesis.get("opens_position") is not False:
        reasons.append("POSITION_STATE_NOT_SEPARATE")
    expires = _utc(thesis.get("expires_at"))
    if expires is None or expires <= now:
        reasons.append("EXPIRED_OR_INVALID_EXPIRY")
    evidence = thesis.get("evidence")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)) or not evidence:
        reasons.append("MISSING_EVIDENCE")
    else:
        for item in evidence:
            if not isinstance(item, Mapping) or any(not str(item.get(k) or "").strip() for k in REQUIRED_EVIDENCE):
                reasons.append("EVIDENCE_PROVENANCE_MISSING")
                continue
            observed = _utc(item.get("observed_at"))
            if observed is None or observed > now or (now - observed).total_seconds() > max_evidence_age_seconds:
                reasons.append("EVIDENCE_STALE_OR_FUTURE")
    if str(thesis.get("state") or "").upper() in {"INVALIDATED", "EXPIRED"}:
        reasons.append("THESIS_NOT_ACTIVE")
    return {
        "valid_for_analyst_review": not reasons,
        "order_authorized": False,
        "reasons": list(dict.fromkeys(reasons)),
        "thesis_id": str(thesis.get("thesis_id") or ""),
    }
