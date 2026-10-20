import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.htf_feed import snapshot,TF_SECONDS

def fetch_ok(symbol,tf,limit,closed_only):
    assert closed_only
    sec=TF_SECONDS[tf]
    return [{"ts":(24*86400//sec-24+i)*sec,"close":100+i} for i in range(24)]

def test_closed_htf_bars():
    x=snapshot("ETHUSDT",24*86400,fetch_ok)
    assert x["direction"]=="LONG"
    assert all(v=="OK" for v in x["data_health"].values())

def test_stale_historical_snapshot_is_unknown():
    x=snapshot("ETHUSDT",100*86400,fetch_ok)
    assert x["direction"]=="UNKNOWN"

def test_future_candles_excluded():
    x=snapshot("ETHUSDT",20*86400,fetch_ok)
    assert x["direction"]=="UNKNOWN"

def test_fetch_failure_unknown():
    def bad(*args,**kwargs): raise ValueError("offline")
    x=snapshot("ETHUSDT",24*86400,bad)
    assert x["direction"]=="UNKNOWN"

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
