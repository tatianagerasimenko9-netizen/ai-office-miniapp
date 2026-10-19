import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.bos_choch_shadow import classify
def sample():
    b=[{"high":10,"low":8,"close":9} for _ in range(18)]
    b[3]={"high":12,"low":8,"close":10}
    b[6]={"high":10,"low":7,"close":9}
    b[9]={"high":11,"low":8,"close":9}
    b[10]={"high":13,"low":9,"close":12.5}
    b[11]={"high":13,"low":8,"close":10}
    b[12]={"high":11,"low":8,"close":9}
    b[13]={"high":11,"low":8,"close":9}
    b[14]={"high":11,"low":6,"close":6.5}
    b[15]={"high":10,"low":6,"close":7}
    b[16]={"high":10,"low":6,"close":7}
    b[17]={"high":10,"low":6,"close":7}
    return b
def test_reversal():
    r=classify(sample(),upto=17)
    assert any(e["label"]=="UNCLASSIFIED" and e["direction"]=="LONG" for e in r["events"]),r
    assert any(e["label"]=="CHOCH" and e["direction"]=="SHORT" for e in r["events"]),r
def test_future_invariance():
    b=sample();a=classify(b,upto=17)
    b.append({"high":999,"low":0,"close":500})
    assert classify(b,upto=17)==a
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
