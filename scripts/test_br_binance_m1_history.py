import sys
from pathlib import Path
from urllib.parse import parse_qs,urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.binance_m1_history import fetch_m1

def fake(url):
    q=parse_qs(urlparse(url).query)
    start=int(q["startTime"][0])
    n=int(q["limit"][0])
    return [[start+i*60000,"100","101","99","100"] for i in range(n)]

def test_paginated_48h():
    x=fetch_m1("ETHUSDT",0,2880*60,fetch_url=fake)
    assert len(x)==2880 and x[0]["ts"]==0 and x[-1]["ts"]==2879*60

def test_bounded():
    try: fetch_m1("ETHUSDT",0,2881*60,fetch_url=fake)
    except ValueError: pass
    else: raise AssertionError("unbounded fetch")

def test_reject_invalid_symbol():
    try: fetch_m1("../USDT",0,60,fetch_url=fake)
    except ValueError: pass
    else: raise AssertionError("invalid symbol")

def test_no_data():
    assert fetch_m1("ETHUSDT",0,120,fetch_url=lambda _:[])==[]

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
