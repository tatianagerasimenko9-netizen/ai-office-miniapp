"""B&R M15 health labels are observational; signal TTL remains 150 seconds."""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br import live


def test_m15_health_boundaries():
    close = 1_000.0
    assert live._m15_health(close, close - 0.001) == "stale"
    assert live._m15_health(close, close) == "fresh"
    assert live._m15_health(close, close + 150) == "fresh"
    assert live._m15_health(close, close + 150.001) == "idle"
    assert live._m15_health(close, close + 900) == "idle"
    assert live._m15_health(close, close + 900.001) == "stale"


def test_signal_gate_stays_strict():
    scanner = inspect.getsource(live.scan_symbol)
    monitor = inspect.getsource(live.monitor)
    assert "now - (t[-1] + 900) > 150" in scanner
    assert 'if health != "fresh":' in monitor
    assert "seen[sym] = ts" in monitor
    assert "scan_idle += 1" in monitor
    assert "scan_stale += 1" in monitor


if __name__ == "__main__":
    test_m15_health_boundaries()
    test_signal_gate_stays_strict()
    print("OK")
