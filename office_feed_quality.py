"""Point-in-time market data quality gates; never infer missing feed health.

Separate freshness and source provenance from a trading signal. A passing
snapshot is evidence for review, not authorization to trade.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping

DEFAULT_MAX_AGE_SECONDS = {"ticker": 30, "orderbook": 5, "liquidations": 120, "news": 300, "ohlcv": 900}


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def assess_feed(
    snapshot: Mapping[str, Any],
    *,
    now_utc: datetime,
    max_age_seconds: int | None = None,
) -> Dict[str, Any]:
    """Fail closed on missing provenance, stale/future timestamps, invalid age."""
    reasons = []
    kind = str(snapshot.get("kind") or "").lower()
    source = str(snapshot.get("source") or "").strip()
    observed = _parse_utc(snapshot.get("observed_at"))
    now = now_utc.astimezone(timezone.utc) if now_utc.tzinfo else None
    if now is None:
        raise ValueError("now_utc must be timezone aware")
    if kind not in DEFAULT_MAX_AGE_SECONDS:
        reasons.append("UNKNOWN_FEED_KIND")
    if not source:
        reasons.append("MISSING_SOURCE")
    if snapshot.get("complete") is not True:
        reasons.append("INCOMPLETE_SNAPSHOT")
    if snapshot.get("is_estimate") is True and kind == "liquidations":
        reasons.append("ESTIMATED_LIQUIDATIONS_NOT_VERIFIED")
    limit = max_age_seconds if max_age_seconds is not None else DEFAULT_MAX_AGE_SECONDS.get(kind)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        reasons.append("INVALID_FRESHNESS_LIMIT")
    if observed is None:
        reasons.append("INVALID_TIMESTAMP")
        age = None
    else:
        age = (now - observed).total_seconds()
        if age < 0:
            reasons.append("FUTURE_TIMESTAMP")
        elif isinstance(limit, int) and limit > 0 and age > limit:
            reasons.append("STALE_SNAPSHOT")
    return {
        "quality": "OK" if not reasons else "UNAVAILABLE",
        "usable_for_review": not reasons,
        "order_authorized": False,
        "age_seconds": age,
        "reasons": reasons,
        "source": source or None,
        "kind": kind,
    }
