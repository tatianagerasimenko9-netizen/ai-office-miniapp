import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.ob_shadow import candidates
def fixture():
    b=[{"open":9,"high":10,"low":8,"close":9} for _ in range(18)]
    b[3]={"open":9,"high":12,"low":8,"close":10}
    b[6]={"open":9,"high":10,"low":7,"close":9}
    b[8]={"open":9.5,"high":10,"low":8,"close":8.5}
    b[9]={"open":9,"high":11,"low":8,"close":9}
    b[10]={"open":9,"high":15,"low":9,"close":14.5}
    return b
def test_candidate():
    r=candidates(fixture(),upto=17)
    assert any(x["direction"]=="LONG" and x["source_i"]==8 for x in r["candidates"]),r
def test_no_future():
    b=fixture();r=candidates(b,upto=17)
    b.append({"open":1,"high":999,"low":0,"close":900})
    assert candidates(b,upto=17)==r
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
