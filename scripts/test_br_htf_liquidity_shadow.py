import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.htf_liquidity_shadow import levels
def candles():
    hi=[10,11,15,12,11,13,12]
    lo=[8,7,6,7,8,7,8]
    return [{"ts":i*3600,"high":h,"low":l} for i,(h,l) in enumerate(zip(hi,lo))]
def test_confirmed_pivot():
    x=levels(candles(),timeframe="1h",asof_ts=8*3600)
    assert x["complete"] and x["pivots_high"][0]["price"]==15
    assert x["pivots_high"][0]["confirmed_ts"]==5*3600
def test_no_future_leak():
    x=levels(candles(),timeframe="1h",asof_ts=4*3600)
    assert x["pivots_high"]==[]
def test_calendar_close_required():
    assert not levels(candles(),timeframe="1w",asof_ts=8*3600)["complete"]
def test_missing_invalid():
    b=candles();b[2]["low"]=-1
    assert not levels(b,timeframe="1h",asof_ts=8*3600)["complete"]
if __name__=="__main__":
    for n,f in list(globals().items()):
        if n.startswith("test_"):f()
    print("OK")
