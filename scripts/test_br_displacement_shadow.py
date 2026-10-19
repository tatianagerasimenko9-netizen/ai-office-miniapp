import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.displacement_shadow import evaluate
def fixture():
    b=[{"open":100,"high":101,"low":99,"close":100} for _ in range(16)]
    b[15]={"open":100,"high":104,"low":99.8,"close":103.8}
    return b
def test_displacement():
    r=evaluate(fixture(),upto=15)
    assert r["displacement_candidate"] and r["direction"]=="LONG"
def test_no_future_leak():
    b=fixture();r=evaluate(b,upto=15)
    b.append({"open":1,"high":999,"low":0,"close":998})
    assert evaluate(b,upto=15)==r
def test_weak_body():
    b=fixture();b[15]={"open":100,"high":101,"low":99,"close":100.2}
    assert not evaluate(b,upto=15)["displacement_candidate"]
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
