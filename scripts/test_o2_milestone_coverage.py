"""Regression: a missing candle window must not create a false NOT_FILLED result."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_signal_track as track
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


def test_mixed_source_cannot_generate_milestone():
    from contextlib import nullcontext
    import tempfile
    from office_bridge import init_office_db
    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "office.db")
        init_office_db(db)
        now = 1_800_000_000.0
        track.record_plan(db, scenario_id="O2|MIXED|LONG", symbol="BTCUSDT", direction="LONG",
                          tf="M15", entry=100, sl=95, tp1=110,
                          confirmed_ts=now - 180, valid_until_ts=now + 1800, confirm_msg_id=123)
        bars = [dict(_bar(now - 180 + i * 60, low=99, high=101), src="binance_futures") for i in range(4)]
        bars[0]["src"] = "binance_spot"
        orig_since, orig_prio = track.milestone_since, track._prio
        try:
            track.milestone_since = lambda db: now - 3600
            track._prio = nullcontext
            track._MS_LAST.clear()
            got = track.pending_milestones(db, fetch=lambda sym, tf, n: bars, now_ts=now, scope="o2")
            assert not got, got
        finally:
            track.milestone_since, track._prio = orig_since, orig_prio
            track._MS_LAST.clear()


if __name__ == "__main__":
    test_missing_early_candles_stays_pending()
    test_complete_candles_expire_unfilled()
    test_middle_gap_stays_pending()
    test_mixed_source_cannot_generate_milestone()
    print("PASS: no false expiry on incomplete market candles")
