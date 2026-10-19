import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.ledger_m1_compare import compare,summarize

S={"sig_id":"X","confirm_ts":0,"direction":"LONG","entry":100,"sl":99,
   "targets":[{"p":101},{"p":102},{"p":103}]}
def bars(seq):
    return [{"ts":900+i*60,"high":hi,"low":lo} for i,(hi,lo) in enumerate(seq)]
def test_match():
    x=compare(S,[{"level":"SL"}],bars([(100.1,99.9),(100.1,98.9)]))
    assert x["verdict"]=="MATCH" and x["m1_status"]=="SL"
def test_mismatch():
    x=compare(S,[{"level":"TP3"}],bars([(100.1,99.9),(100.1,98.9)]))
    assert x["verdict"]=="MISMATCH"
def test_same_bar_ambiguity():
    x=compare(S,[{"level":"TP3"}],bars([(103.1,99.9)]))
    assert x["verdict"]=="REVIEW"
def test_missing_first_bar():
    x=compare(S,[],[{"ts":960,"high":100.1,"low":99.9}])
    assert x["verdict"]=="INSUFFICIENT_M1"
def test_gap_review():
    x=compare(S,[],[{"ts":900,"high":100.1,"low":99.9},
                     {"ts":1020,"high":100.1,"low":98.9}])
    assert x["verdict"]=="REVIEW"
def test_summary():
    assert summarize([{"verdict":"MATCH"},{"verdict":"MISMATCH"}])["verdicts"]["MISMATCH"]==1
if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
