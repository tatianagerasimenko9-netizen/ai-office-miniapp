"""Політика Telegram для подій рівня: лише нумеровані Office2 READY; збій номера не губить подію."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office2.milestone_policy import DB_ONLY, RETRY, SEND, decide


def _m(**kw):
    return dict({"scenario_id": "O2|abc|1", "level": "TP1", "symbol": "BTCUSDT"}, **kw)


def test_numbered_o2_is_sent():
    assert decide("o2", _m(), lambda s: 4) == (SEND, 4, "numbered")


def test_unnumbered_o2_is_db_only():
    assert decide("o2", _m(), lambda s: None)[0] == DB_ONLY


def test_legacy_scope_never_sent_even_if_numbered():
    assert decide("other", _m(), lambda s: 9)[0] == DB_ONLY


def test_silent_and_legacy_quiet_are_db_only():
    assert decide("o2", _m(silent=True), lambda s: 4)[0] == DB_ONLY
    assert decide("other", _m(), lambda s: 4, legacy_quiet=True)[0] == DB_ONLY


def test_number_lookup_failure_retries_not_drops():
    def boom(_):
        raise RuntimeError("db busy")

    act, no, why = decide("o2", _m(), boom)
    assert act == RETRY and no is None and "RuntimeError" in why


def test_tp_and_sl_of_numbered_plan_both_sent():
    for lvl in ("TP1", "TP2", "TP3", "SL"):
        assert decide("o2", _m(level=lvl), lambda s: 7)[0] == SEND


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("OK")
