#!/usr/bin/env python3
"""Offline feed freshness tests; no market network or exchange."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office_feed_quality import assess_feed

now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
feed = {"kind":"orderbook", "source":"exchange-depth", "complete":True, "observed_at":(now-timedelta(seconds=2)).isoformat()}
def check(**changes):
    return assess_feed({**feed, **changes}, now_utc=now)
assert check()["usable_for_review"] and not check()["order_authorized"]
assert "MISSING_SOURCE" in check(source="")["reasons"]
assert "INCOMPLETE_SNAPSHOT" in check(complete=False)["reasons"]
assert "STALE_SNAPSHOT" in check(observed_at=(now-timedelta(seconds=6)).isoformat())["reasons"]
assert "FUTURE_TIMESTAMP" in check(observed_at=(now+timedelta(seconds=1)).isoformat())["reasons"]
assert "INVALID_TIMESTAMP" in check(observed_at="bad")["reasons"]
assert "UNKNOWN_FEED_KIND" in check(kind="unknown")["reasons"]
assert "ESTIMATED_LIQUIDATIONS_NOT_VERIFIED" in check(kind="liquidations", is_estimate=True)["reasons"]
assert "INVALID_FRESHNESS_LIMIT" in assess_feed(feed, now_utc=now, max_age_seconds=0)["reasons"]
print("OK feed quality: freshness, provenance, completeness, estimated liquidation veto")
