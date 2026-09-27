#!/usr/bin/env python3
"""Offline tests for thesis evidence and expiry; no network or orders."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office_market_thesis import evaluate_thesis

now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
thesis = {
    "thesis_id": "T1", "regime": "RANGE", "state": "WATCHING",
    "hypothesis": "Test upper range", "alternative": "Acceptance above range",
    "invalidation": "H1 close above range", "opens_position": False,
    "expires_at": (now + timedelta(hours=1)).isoformat(),
    "evidence": [{"source": "closed H1 candle", "observed_at": (now-timedelta(minutes=2)).isoformat(), "timeframe": "H1", "fact": "range high tested"}],
}
def check(**changes):
    return evaluate_thesis({**thesis, **changes}, now_utc=now)
assert check()["valid_for_analyst_review"] and not check()["order_authorized"]
assert "REGIME_NOT_VERIFIED" in check(regime="UNKNOWN")["reasons"]
assert "MISSING_ALTERNATIVE" in check(alternative="")["reasons"]
assert "EXPIRED_OR_INVALID_EXPIRY" in check(expires_at=now.isoformat())["reasons"]
assert "POSITION_STATE_NOT_SEPARATE" in check(opens_position=True)["reasons"]
assert "MISSING_EVIDENCE" in check(evidence=[])["reasons"]
assert "EVIDENCE_PROVENANCE_MISSING" in check(evidence=[{"source":"x"}])["reasons"]
assert "EVIDENCE_STALE_OR_FUTURE" in check(evidence=[dict(thesis["evidence"][0], observed_at=(now-timedelta(hours=2)).isoformat())])["reasons"]
assert "EVIDENCE_STALE_OR_FUTURE" in check(evidence=[dict(thesis["evidence"][0], observed_at=(now+timedelta(seconds=1)).isoformat())])["reasons"]
assert "THESIS_NOT_ACTIVE" in check(state="INVALIDATED")["reasons"]
print("OK market thesis: provenance, expiry, evidence freshness, invalidation, no orders")
