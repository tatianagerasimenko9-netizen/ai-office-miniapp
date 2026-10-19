"""Behavioral regression for closed-M15 freshness; independent of source spelling."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.feed_health import classify

def test_closed_bar_is_eligible_through_m15_period():
    assert classify(900,1800)["allow_new_signals"]
    assert classify(900,2699)["allow_new_signals"]
    assert not classify(900,2701)["allow_new_signals"]

def test_closed_bar_not_used_before_close():
    assert not classify(900,1799)["allow_new_signals"]
    assert classify(900,1799)["state"]=="NOT_CLOSED"

if __name__=="__main__":
    test_closed_bar_is_eligible_through_m15_period()
    test_closed_bar_not_used_before_close()
    print("OK")
