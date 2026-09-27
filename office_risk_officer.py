"""Read-only, fail-closed preflight for proposed (not executed) trade plans.

No database migration, exchange access, Telegram, or order placement.
This is a deterministic risk veto; it does not score signal profitability.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional


def _positive(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def review_plan(
    plan: Mapping[str, Any],
    *,
    equity_usdt: Any,
    max_risk_pct: Any,
    existing_risk_usdt: Any = 0,
    max_portfolio_risk_pct: Any = 2,
    data_quality: str = "UNAVAILABLE",
    context_quality: str = "UNAVAILABLE",
    execution_quality: str = "UNAVAILABLE",
) -> Dict[str, Any]:
    """Return a deterministic approval/veto for a *hypothetical* plan.

    Rejects missing/invalid information. Approval never authorizes an order.
    The caller must independently verify the actual position and live fill.
    """
    reasons = []
    side = str(plan.get("direction") or "").upper()
    entry = _positive(plan.get("entry"))
    stop = _positive(plan.get("sl"))
    target = _positive(plan.get("tp1"))
    quantity = _positive(plan.get("quantity"))
    equity = _positive(equity_usdt)
    risk_pct = _positive(max_risk_pct)
    portfolio_pct = _positive(max_portfolio_risk_pct)
    try:
        existing = float(existing_risk_usdt)
    except (TypeError, ValueError, OverflowError):
        existing = float("nan")
    if side not in ("LONG", "SHORT"):
        reasons.append("INVALID_DIRECTION")
    if None in (entry, stop, target, quantity):
        reasons.append("INCOMPLETE_PLAN")
    elif side == "LONG" and not (stop < entry < target):
        reasons.append("INVALID_LONG_GEOMETRY")
    elif side == "SHORT" and not (target < entry < stop):
        reasons.append("INVALID_SHORT_GEOMETRY")
    if equity is None or risk_pct is None or portfolio_pct is None:
        reasons.append("INVALID_RISK_LIMIT")
    if not math.isfinite(existing) or existing < 0:
        reasons.append("INVALID_EXISTING_RISK")
    for label, quality in (
        ("DATA", data_quality), ("CONTEXT", context_quality),
        ("EXECUTION", execution_quality),
    ):
        if quality != "OK":
            reasons.append(label + "_NOT_VERIFIED")
    estimated_risk = None
    if entry is not None and stop is not None and quantity is not None:
        estimated_risk = abs(entry - stop) * quantity
        if equity is not None and risk_pct is not None:
            if estimated_risk > equity * risk_pct / 100:
                reasons.append("TRADE_RISK_LIMIT")
        if equity is not None and portfolio_pct is not None and math.isfinite(existing) and existing >= 0:
            if estimated_risk + existing > equity * portfolio_pct / 100:
                reasons.append("PORTFOLIO_RISK_LIMIT")
    return {
        "approved_for_review": not reasons,
        "order_authorized": False,
        "reasons": reasons,
        "estimated_risk_usdt": estimated_risk,
        "existing_risk_usdt": existing if math.isfinite(existing) and existing >= 0 else None,
    }
