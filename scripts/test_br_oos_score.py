import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.oos_score import evaluate

def test_late_period_failure_blocks():
    rows=[{"created_ts":i,"status":"TP3" if i<20 else "SL","selected":True} for i in range(40)]
    x=evaluate(rows,lambda r:r["selected"])
    assert x["train"]["tp3"]==20 and x["test"]["sl"]==20
    assert not x["eligible_for_live_review"]

def test_tiny_winning_test_blocks():
    rows=[{"created_ts":i,"status":"TP3","selected":i>=20} for i in range(40)]
    x=evaluate(rows,lambda r:r["selected"],min_test=25)
    assert not x["eligible_for_live_review"]

def test_no_outcomes():
    assert evaluate([],lambda r:True)["test"]["tp3_pct"] is None

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
