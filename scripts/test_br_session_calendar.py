"""Offline regression tests: B&R calendar and DST phase classification."""
import sys
from pathlib import Path
from datetime import datetime, timezone

# Direct script execution by full-regression CI needs the repository root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.session_calendar import classify_us_equity_clock as phase


def at(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def test_weekend_not_us_regular():
    assert phase(at("2026-10-17T19:41:00+00:00"))["phase"] == "WEEKEND"


def test_premarket_and_regular_boundaries():
    assert phase(at("2026-10-19T13:29:00+00:00"))["phase"] == "PREMARKET"
    assert phase(at("2026-10-19T13:30:00+00:00"))["phase"] == "REGULAR"
    assert phase(at("2026-10-19T20:00:00+00:00"))["phase"] == "AFTERHOURS"


def test_us_dst_transition_independent_of_kyiv():
    # On 26 October Kyiv has changed clocks; NY has not yet.
    assert phase(at("2026-10-26T13:29:00+00:00"))["phase"] == "PREMARKET"
    assert phase(at("2026-10-26T13:30:00+00:00"))["phase"] == "REGULAR"
    # NY switches to EST on 1 November 2026.
    assert phase(at("2026-11-02T14:29:00+00:00"))["phase"] == "PREMARKET"
    assert phase(at("2026-11-02T14:30:00+00:00"))["phase"] == "REGULAR"


def test_no_claim_of_verified_exchange_calendar():
    result = phase(at("2026-10-19T13:30:00+00:00"))
    assert result["calendar_verified"] is False
    assert result["scope"] == "SHADOW_ONLY"
