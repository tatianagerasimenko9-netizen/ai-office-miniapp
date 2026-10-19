import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.structure_events_shadow import analyze
def fixture():
    b=[{"high":10,"low":8,"close":9} for _ in range(12)]
    b[3]={"high":12,"low":8,"close":10}
    b[4]={"high":10,"low":8,"close":9}
    b[5]={"high":10,"low":8,"close":9}
    b[6]={"high":10,"low":8,"close":9}
    b[7]={"high":11,"low":8,"close":9}
    b[8]={"high":11,"low":8,"close":9}
    b[9]={"high":11,"low":8,"close":9}
    b[10]={"high":11,"low":8,"close":9}
    b[11]={"high":13,"low":10,"close":12.5}
    return b
def test_causal_break():
    x=analyze(fixture(),upto=11)
    assert any(e["type"]=="STRUCTURE_BREAK" and e["direction"]=="LONG" for e in x["events"])
def test_no_future():
    b=fixture();x=analyze(b,upto=11)
    b.append({"high":100000,"low":0,"close":999})
    assert analyze(b,upto=11)==x
def test_sweep():
    b=fixture();b[11]={"high":13,"low":9,"close":11}
    x=analyze(b,upto=11)
    assert any(e["type"]=="LIQUIDITY_SWEEP" for e in x["events"])
def test_fvg():
    b=fixture();b[11]={"high":15,"low":12,"close":14}
    x=analyze(b,upto=11)
    assert any(e["type"]=="FVG" and e["direction"]=="LONG" for e in x["events"])
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
