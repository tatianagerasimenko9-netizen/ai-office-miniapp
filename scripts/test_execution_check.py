#!/usr/bin/env python3
"""Execution Planner v1 checks: late entry, RR from actual price, invalidation, duplicates. Offline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office_execution_check import execution_checks  # noqa: E402

base = dict(symbol="SOLUSDT", direction="LONG", zone_lo=140, zone_hi=142, sl=136, tp1=150,
            price_fresh=True, has_open_position=False, min_rr=1.5, min_tp1_pct=3.0)


def st(res, key):
    return next(c["state"] for c in res["checks"] if c["key"] == key)


r = execution_checks(price=141, **base)
assert st(r, "late") == "OK" and st(r, "rr") == "OK" and st(r, "invalidation") == "OK"
assert r["verdict"] == "NOT_VERIFIED", "spread/news are unknown, never 'checked'"
assert r["order_authorized"] is False
late = execution_checks(price=147, **base)
assert st(late, "late") == "FAIL" and late["verdict"] == "BLOCKED"
dead = execution_checks(price=135, **base)
assert st(dead, "invalidation") == "FAIL"
bad_rr = execution_checks(price=141, **{**base, "tp1": 145})
assert st(bad_rr, "rr") == "FAIL" and st(bad_rr, "space") == "FAIL"
dup = execution_checks(price=141, **{**base, "has_open_position": True})
assert st(dup, "duplicate") == "FAIL"
unk = execution_checks(price=None, **{**base, "price_fresh": False, "has_open_position": None})
assert st(unk, "data") == "UNAVAILABLE" and st(unk, "duplicate") == "UNAVAILABLE"
assert not any(c["key"] == "rr" for c in unk["checks"]), "no price -> no invented RR"
short = execution_checks(price=2665, **{**base, "symbol": "ETHUSDT", "direction": "SHORT", "zone_lo": 2662,
                                        "zone_hi": 2668, "sl": 2686, "tp1": 2600, "min_tp1_pct": 1.2})
assert st(short, "rr") == "OK" and st(short, "late") == "OK", short
print("OK Execution Planner v1: late entry, actual-price RR, invalidation, duplicates, unknown stays unknown")
