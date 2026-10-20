import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.feed_health import classify,aggregate

def test_fresh_closed_bar():
    assert classify(900,1800)["allow_new_signals"]
def test_stale_cannot_trigger():
    assert classify(900,2701)["state"]=="STALE"
    assert not classify(900,2701)["allow_new_signals"]
def test_not_closed_cannot_trigger():
    assert classify(900,1799)["state"]=="NOT_CLOSED"
def test_degraded():
    report=aggregate({"BTC":classify(900,1800),"ETH":classify(900,2701)})
    assert report["degraded"] and not report["ready"]
if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"):fn()
