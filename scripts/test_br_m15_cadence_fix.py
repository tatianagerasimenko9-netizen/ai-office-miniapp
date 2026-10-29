"""B&R M15 signal freshness must match the READY delivery window (not Office2)."""
import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br import live


def _bars_with_last_close_age(now, age_seconds):
    last_open = now - 900 - age_seconds
    return [
        {
            "ts": datetime.fromtimestamp(last_open - (99 - i) * 900, timezone.utc).isoformat(),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        }
        for i in range(100)
    ]


def test_m15_signal_freshness_matches_ready_delivery_window():
    scan = inspect.getsource(live.scan_symbol)
    deliver = inspect.getsource(live.deliver)
    monitor = inspect.getsource(live.monitor)
    assert "now - (t[-1] + 900) > 240" in scan
    assert 'time.time() - (float(row["confirm_ts"]) + 900) > 240' in deliver
    # Feed health can still recognise the latest closed M15 bar for up to a
    # candle period; signal creation itself is stricter because READY expires sooner.
    assert "now_ts - (ts + 900) >= 900" in monitor
    assert "> 150" not in scan
    assert "> 150" not in monitor


def test_scan_symbol_rejects_bar_past_ready_window():
    now = datetime(2026, 10, 29, 1, 0, tzinfo=timezone.utc).timestamp()
    bars = _bars_with_last_close_age(now, 241)
    fetch = lambda *args, **kwargs: bars
    with patch.object(live.detect, "scan", side_effect=AssertionError("stale bars must not reach detector")):
        assert live.scan_symbol("no-db", "BTCUSDT", fetch, now=now) == 0


def test_scan_symbol_accepts_bar_inside_ready_window():
    now = datetime(2026, 10, 29, 1, 0, tzinfo=timezone.utc).timestamp()
    bars = _bars_with_last_close_age(now, 239)
    fetch = lambda *args, **kwargs: bars
    with patch.object(live.detect, "scan", return_value=[]) as detector:
        assert live.scan_symbol("no-db", "BTCUSDT", fetch, now=now) == 0
        detector.assert_called_once()


def test_stale_feed_is_observable():
    assert "DEGRADED_FEED" in inspect.getsource(live.monitor)


if __name__ == "__main__":
    test_m15_signal_freshness_matches_ready_delivery_window()
    test_scan_symbol_rejects_bar_past_ready_window()
    test_scan_symbol_accepts_bar_inside_ready_window()
    test_stale_feed_is_observable()
    print("OK")
