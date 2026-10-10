"""Regression: a missing candle window must not create a false NOT_FILLED result."""
from __future__ import annotations

from datetime import datetime, timezone
from office_signal_track import simulate


def _bar(ts, low=99.0, high=99.5):
    return {"ts": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(), "low": low, "high": high}


def test_missing_early_candles_stays_pending():
    p = {"direction": "LONG", "entry": 100, "sl": 95, "tp1": 110,
         "confirmed_ts": 0, "valid_until_ts": 600}
    candles = [_bar(t) for t in (420, 480, 540, 600)]
    assert simulate(p, candles, now_ts=720, tf_sec=60)["status"] == "PENDING"


def test_complete_candles_expire_unfilled():
    p = {"direction": "LONG", "entry": 100, "sl": 95, "tp1": 110,
         "confirmed_ts": 0, "valid_until_ts": 600}
    candles = [_bar(t) for t in range(0, 661, 60)]
    assert simulate(p, candles, now_ts=720, tf_sec=60)["status"] == "NOT_FILLED"


def test_middle_gap_stays_pending():
    p = {"direction": "LONG", "entry": 100, "sl": 95, "tp1": 110,
         "confirmed_ts": 0, "valid_until_ts": 600}
    candles = [_bar(t) for t in list(range(0, 241, 60)) + list(range(420, 661, 60))]
    assert simulate(p, candles, now_ts=720, tf_sec=60)["status"] == "PENDING"


if __name__ == "__main__":
    test_missing_early_candles_stays_pending()
    test_complete_candles_expire_unfilled()
    test_middle_gap_stays_pending()
    print("PASS: no false expiry on incomplete market candles")
