import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.analyst_evidence import labels, evaluate

def test_no_entry_no_label():
    s = [{"sig_id":"a","confirm_ts":1,"symbol":"ETHUSDT","direction":"LONG","entry":100,"sl":99,"tp1":102}]
    assert labels(s,[{"sig_id":"a","level":"TP1","touched_ts":3}]) == []

def test_ambiguous_excluded():
    s = [{"sig_id":"a","confirm_ts":1,"symbol":"ETHUSDT","direction":"LONG","entry":100,"sl":99,"tp1":102}]
    ev = [{"sig_id":"a","level":level,"touched_ts":ts} for level,ts in [("ENTRY",2),("TP1",3),("SL",3)]]
    assert labels(s,ev) == []

def test_first_stop_loss():
    s = [{"sig_id":"a","confirm_ts":1,"symbol":"ETHUSDT","direction":"LONG","entry":100,"sl":99,"tp1":102}]
    ev = [{"sig_id":"a","level":level,"touched_ts":ts} for level,ts in [("ENTRY",2),("SL",3),("TP1",4)]]
    assert labels(s,ev)[0]["r"] == -1.0

def test_small_sample_no_training():
    assert evaluate([])["status"] == "INSUFFICIENT_EVIDENCE"
    assert evaluate([])["trained"] is False

def test_future_outcome_purged():
    rows = [{"sig_id":str(i),"confirm_ts":i,"outcome_ts":i+1000,"r":1,"won":True} for i in range(200)]
    assert evaluate(rows)["status"] == "INSUFFICIENT_EVIDENCE"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK")
