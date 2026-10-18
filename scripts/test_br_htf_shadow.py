import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.htf_shadow import classify

def bars(step, n=21, start=100):
    return [{"ts":i*step,"close":start+i} for i in range(n)]

def test_bullish_alignment():
    x=classify({"1d":bars(86400),"4h":bars(14400),"1h":bars(3600)},confirm_ts=22*86400)
    assert x["direction"]=="LONG"

def test_future_bar_fail_closed():
    x=classify({"1d":bars(86400),"4h":bars(14400),"1h":bars(3600)},confirm_ts=20*86400)
    assert x["direction"]=="UNKNOWN"

def test_missing_tf_fail_closed():
    x=classify({"1d":bars(86400),"4h":bars(14400)},confirm_ts=22*86400)
    assert x["direction"]=="UNKNOWN"

def test_mixed():
    down=[dict(x,close=200-i) for i,x in enumerate(bars(3600))]
    x=classify({"1d":bars(86400),"4h":bars(14400),"1h":down},confirm_ts=22*86400)
    assert x["direction"]=="MIXED"

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
