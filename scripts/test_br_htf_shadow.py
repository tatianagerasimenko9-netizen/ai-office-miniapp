import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.htf_shadow import classify,classify_extended

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

def test_missing_close_is_unknown():
    broken=bars(86400)
    broken[-1].pop("close")
    x=classify({"1d":broken,"4h":bars(14400),"1h":bars(3600)},confirm_ts=22*86400)
    assert x["direction"]=="UNKNOWN"

def test_mixed():
    down=[dict(x,close=200-i) for i,x in enumerate(bars(3600))]
    x=classify({"1d":bars(86400),"4h":bars(14400),"1h":down},confirm_ts=22*86400)
    assert x["direction"]=="MIXED"

def test_extended_missing_calendar_closes():
    x=classify_extended({"1M":bars(86400),"1w":bars(86400),
       "1d":bars(86400),"4h":bars(14400),"1h":bars(3600)},confirm_ts=22*86400)
    assert x["direction"]=="UNKNOWN"
    assert x["by_timeframe"]["1M"]=="UNKNOWN"
def test_extended_complete():
    monthly=[dict(b,close_ts=b["ts"]+1) for b in bars(86400)]
    weekly=[dict(b,close_ts=b["ts"]+1) for b in bars(86400)]
    x=classify_extended({"1M":monthly,"1w":weekly,"1d":bars(86400),
       "4h":bars(14400),"1h":bars(3600)},confirm_ts=22*86400)
    assert x["direction"]=="LONG"
def test_extended_future_calendar_close():
    monthly=[dict(b,close_ts=b["ts"]+1) for b in bars(86400)]
    monthly[-1]["close_ts"]=23*86400
    x=classify_extended({"1M":monthly,"1w":monthly,"1d":bars(86400),
       "4h":bars(14400),"1h":bars(3600)},confirm_ts=22*86400)
    assert x["direction"]=="UNKNOWN"
if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
