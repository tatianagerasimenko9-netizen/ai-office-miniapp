import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.tp3_shadow import evaluate

def test_exploratory_only():
    s={"symbol":"ADAUSDT","direction":"LONG","entry":100,"sl":99,
       "targets":[{"p":100.5},{"p":101},{"p":101.4}]}
    x=evaluate(s)
    assert x["exploratory_shortlist"] and x["mode"]=="SHADOW_ONLY" and not x["live_gate"]

def test_high_rr_not_shortlisted():
    s={"symbol":"ADAUSDT","direction":"LONG","entry":100,"sl":99,
       "targets":[{"p":101},{"p":102},{"p":104}]}
    assert not evaluate(s)["exploratory_shortlist"]

def test_invalid_geometry():
    s={"symbol":"ADAUSDT","direction":"LONG","entry":100,"sl":101,
       "targets":[{"p":101},{"p":102},{"p":103}]}
    assert not evaluate(s)["valid"]

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
