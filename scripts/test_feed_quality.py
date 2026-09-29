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

# Live gate: stale/missing LTF data turns a new SEND into WAIT; nothing else changes.
import os as _os
from datetime import timedelta as _td
from office_feed_quality import gate_send_on_fresh_data as _gate

_now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
_fresh = [{"ts": (_now - _td(minutes=20)).isoformat()}, {"ts": (_now - _td(minutes=5)).isoformat()}]
_stale = [{"ts": (_now - _td(hours=3)).isoformat()}]
_send = {"action": "SEND", "send": True, "reason": "ok"}
assert _gate(_send, _fresh, interval="15m", now_utc=_now)["send"] is True
_w = _gate(_send, _stale, interval="15m", now_utc=_now)
assert _w["action"] == "WAIT" and not _w["send"] and "STALE_SNAPSHOT" in _w["reason"], _w
assert _gate(_send, None, now_utc=_now)["action"] == "WAIT"
_wait = {"action": "WATCHING", "send": False}
assert _gate(_wait, None, now_utc=_now) == _wait, "non-SEND decisions untouched"
_os.environ["OFFICE_FEED_GATE"] = "0"
assert _gate(_send, _stale, now_utc=_now)["send"] is True
_os.environ.pop("OFFICE_FEED_GATE")
print("OK live feed gate: stale LTF blocks new SEND only; OFFICE_FEED_GATE=0 rollback")
