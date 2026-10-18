import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.reconcile_shadow import reconcile
S={"direction":"LONG","entry":100,"sl":99,"targets":[{"p":101},{"p":102},{"p":103}]}
def b(t,lo,hi): return {"ts":t,"low":lo,"high":hi}
def e(level): return {"level":level}

def test_match():
    x=reconcile(S,[b(0,99.9,100.1),b(60,100.1,103.1)],
                [e("ENTRY"),e("TP1"),e("TP2"),e("TP3")])
    assert x["verdict"]=="MATCH"

def test_mismatch():
    x=reconcile(S,[b(0,99.9,100.1),b(60,98.9,100)],
                [e("ENTRY"),e("TP1")])
    assert x["verdict"]=="MISMATCH"

def test_gap_not_assumed_loss():
    x=reconcile(S,[b(0,99.9,100.1),b(120,98.9,100)],[e("ENTRY"),e("SL")])
    assert x["verdict"]=="UNVERIFIABLE"

def test_incomplete_not_assumed():
    x=reconcile(S,[b(0,99.9,100.1)],[e("ENTRY")])
    assert x["verdict"]=="INCOMPLETE"

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
