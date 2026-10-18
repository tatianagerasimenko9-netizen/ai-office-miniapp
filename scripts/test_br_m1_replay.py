import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.m1_replay import replay

S={"direction":"LONG","entry":100,"sl":99,"targets":[{"p":101},{"p":102},{"p":103}]}
def b(ts,lo,hi): return {"ts":ts,"low":lo,"high":hi}

def test_win(): assert replay(S,[b(0,99.9,100.1),b(60,100.1,103.1)])["status"]=="TP3"
def test_stop(): assert replay(S,[b(0,99.9,100.1),b(60,98.9,100)])["status"]=="SL"
def test_same_bar_ambiguous(): assert replay(S,[b(0,98.9,101.1)])["status"]=="AMBIGUOUS"
def test_stop_tp_same_bar(): assert replay(S,[b(0,99.9,100.1),b(60,98.9,101.1)])["status"]=="AMBIGUOUS"
def test_gap(): assert replay(S,[b(0,99.9,100.1),b(120,100.1,103.1)])["status"]=="DATA_GAP"
def test_no_entry(): assert replay(S,[b(0,101.1,102.2)])["status"]=="UNFILLED"
def test_invalid(): assert replay(dict(S,sl=101),[])["status"]=="INVALID"
def test_no_hindsight_entry():
    s=dict(S,eligible_ts=60)
    assert replay(s,[b(0,99.9,100.1),b(60,100.2,100.5)])["status"]=="UNFILLED"

def test_short():
    s={"direction":"SHORT","entry":100,"sl":101,"targets":[{"p":99},{"p":98},{"p":97}]}
    assert replay(s,[b(0,99.9,100.1),b(60,96.9,99.9)])["status"]=="TP3"

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
