import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.breaker_shadow import breakers
def ob():return {"low":99,"high":101,"confirmed_ts":60,"direction":"LONG"}
def bar(ts,close):return {"ts":ts,"close_ts":ts+60,"close":close}
def test_breaker_only_after_closed_candle():
    x=breakers([ob()],[bar(60,98)],asof_ts=120)
    assert len(x)==1 and x[0]["direction"]=="SHORT"
def test_no_future_leak():
    assert not breakers([ob()],[bar(60,98)],asof_ts=119)
def test_wick_not_close():
    assert not breakers([ob()],[bar(60,100)],asof_ts=120)
def test_no_prior_candle():
    assert not breakers([ob()],[bar(0,98)],asof_ts=120)
def test_short_to_long():
    o=ob();o["direction"]="SHORT"
    assert breakers([o],[bar(60,102)],asof_ts=120)[0]["direction"]=="LONG"
if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"):fn()
    print("OK")
