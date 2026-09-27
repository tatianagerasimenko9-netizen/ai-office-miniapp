#!/usr/bin/env python3
"""Offline deterministic risk-veto regression; no exchange or Telegram."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office_risk_officer import review_plan

plan = dict(direction="LONG", entry=100, sl=99, tp1=103, quantity=5)
quality = dict(data_quality="OK", context_quality="OK", execution_quality="OK")
base = dict(equity_usdt=1000, max_risk_pct=1, max_portfolio_risk_pct=2)
def check(p=plan, **kwargs):
    return review_plan(p, **{**base, **quality, **kwargs})

ok = check()
assert ok["approved_for_review"] and not ok["order_authorized"] and ok["estimated_risk_usdt"] == 5
assert not check(data_quality="DEGRADED")["approved_for_review"]
assert not check(context_quality="UNAVAILABLE")["approved_for_review"]
assert not check(execution_quality="UNAVAILABLE")["approved_for_review"]
assert "TRADE_RISK_LIMIT" in check(dict(plan, quantity=11))["reasons"]
assert "PORTFOLIO_RISK_LIMIT" in check(existing_risk_usdt=16)["reasons"]
assert "INVALID_EXISTING_RISK" in check(existing_risk_usdt=-1)["reasons"]
assert "INVALID_RISK_LIMIT" in check(max_risk_pct=float("nan"))["reasons"]
assert "INCOMPLETE_PLAN" in check(dict(plan, sl=None))["reasons"]
assert "INVALID_LONG_GEOMETRY" in check(dict(plan, sl=101))["reasons"]
assert "INVALID_SHORT_GEOMETRY" in check(dict(plan, direction="SHORT"))["reasons"]
assert check(dict(direction="SHORT", entry=100, sl=101, tp1=97, quantity=5))["approved_for_review"]
assert "INCOMPLETE_PLAN" in check(dict(plan, quantity=float("inf")))["reasons"]
print("OK risk officer: valid plans, risk caps, quality veto, geometry, NaN/inf, no orders")
