import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.m1_coverage_shadow import audit_m1
def b(t):return {"ts":t,"open":10,"high":11,"low":9,"close":10}
def test_complete():
    assert audit_m1([b(0),b(60)],start_ts=0,end_ts=120)["complete"]
def test_missing():
    r=audit_m1([b(0)],start_ts=0,end_ts=120)
    assert r["missing"]==1 and not r["complete"]
def test_duplicate():
    assert audit_m1([b(0),b(0)],start_ts=0,end_ts=60)["duplicate"]==1
def test_invalid_ohlc():
    x=b(0);x["high"]=8
    assert audit_m1([x],start_ts=0,end_ts=60)["invalid"]==1
def test_outside():
    assert audit_m1([b(0),b(60)],start_ts=0,end_ts=60)["outside"]==1
if __name__=="__main__":
    for n,f in list(globals().items()):
        if n.startswith("test_"):f()
    print("OK")
