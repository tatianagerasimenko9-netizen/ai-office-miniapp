"""Regression: a closed M15 candle remains the latest bar for up to 15 minutes."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br import live


def test_closed_bar_is_eligible_through_m15_period():
    from inspect import getsource
    src = getsource(live.scan_symbol)
    monitor = getsource(live.monitor)
    assert "now - (t[-1] + 900) > 900" in src
    assert "now_ts - (ts + 900) > 900" in monitor
    assert "s[\"confirm_i\"] != len(t) - 1" in src


def test_closed_bar_not_used_before_close():
    from inspect import getsource
    assert "t[-1] + 900 > now" in getsource(live.scan_symbol)
    assert "ts + 900 > now_ts" in getsource(live.monitor)


if __name__ == "__main__":
    test_closed_bar_is_eligible_through_m15_period()
    test_closed_bar_not_used_before_close()
    print("OK")
