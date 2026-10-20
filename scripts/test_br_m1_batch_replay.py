import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.m1_batch_replay import run

def sig(sid="S",status="SL"):
    return {"sig_id":sid,"symbol":"ETHUSDT","confirm_ts":0,"created_ts":900,
            "status":status,"direction":"LONG","entry":100,"sl":99,
            "targets_json":'[{"p":101},{"p":102},{"p":103}]'}

def fetch(symbol,start,end):
    assert symbol=="ETHUSDT" and start==900 and end==900+48*3600
    return [{"ts":900,"high":100.1,"low":99.9},
            {"ts":960,"high":100.1,"low":98.9}]

def test_match():
    x=run([sig()],[{"sig_id":"S","level":"SL"}],fetch=fetch)
    assert x["summary"]["verdicts"]["M1_DATA_INCOMPLETE"]==1

def test_mismatch():
    x=run([sig("T","TP3")],[{"sig_id":"T","level":"TP3"}],fetch=fetch)
    assert x["summary"]["verdicts"]["M1_DATA_INCOMPLETE"]==1

def test_skips_active():
    x=run([sig(status="SENT")],[],fetch=lambda *args: (_ for _ in ()).throw(Exception()))
    assert x["summary"]["total"]==0

def test_fetch_failure():
    def fail(*args): raise OSError("offline")
    x=run([sig()],[],fetch=fail)
    assert x["summary"]["verdicts"]["FETCH_OR_INPUT_ERROR"]==1

def test_batch_limit():
    try: run([sig(str(i)) for i in range(501)],[],fetch=fetch)
    except ValueError: pass
    else: raise AssertionError("batch not bounded")

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
