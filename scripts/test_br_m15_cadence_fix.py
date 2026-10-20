"""B&R closed-M15 cadence regression (not Office2)."""
import inspect
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br import live

def test_m15_valid_for_full_candle_period():
    scan=inspect.getsource(live.scan_symbol)
    monitor=inspect.getsource(live.monitor)
    assert "now - (t[-1] + 900) >= 900" in scan
    assert "now_ts - (ts + 900) >= 900" in monitor
    assert "> 150" not in scan
    assert "> 150" not in monitor

def test_stale_feed_is_observable():
    assert "DEGRADED_FEED" in inspect.getsource(live.monitor)

if __name__=="__main__":
    test_m15_valid_for_full_candle_period()
    test_stale_feed_is_observable()
    print("OK")
