import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.regime_shadow import assess

S={"direction":"LONG"}
def test_trend_clear():
    x=assess(S,{"direction":"LONG"},{"valid":True,"obstacle_r":2})
    assert x["candidate_for_research"] and not x["live_gate"]

def test_countertrend():
    x=assess(S,{"direction":"SHORT"},{"valid":True,"obstacle_r":2})
    assert x["regime"]=="COUNTERTREND" and not x["candidate_for_research"]

def test_near_obstacle():
    x=assess(S,{"direction":"LONG"},{"valid":True,"obstacle_r":1})
    assert x["clearance"]=="NEAR_OBSTACLE" and not x["candidate_for_research"]

def test_unknown_fail_closed():
    x=assess(S,{"direction":"UNKNOWN"},{"valid":True,"obstacle_r":None})
    assert x["regime"]=="UNKNOWN" and x["clearance"]=="UNKNOWN"
    assert not x["candidate_for_research"]

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
