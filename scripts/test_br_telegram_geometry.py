import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.telegram_geometry import validate
def example():
    return {"direction":"LONG","entry":5.065,"sl":4.996,"tp1":5.135,"tp2":5.198,"tp3":5.391}
def test_net_rr_not_gross():
    a=validate(example(),round_trip_cost_pct=0)
    b=validate(example(),round_trip_cost_pct=0.1)
    assert b["tp1_net_r"]<a["tp1_net_r"]
def test_wrong_side():
    x=example();x["sl"]=5.1
    try:validate(x,round_trip_cost_pct=0.1)
    except ValueError:return
    assert False
def test_short():
    x={"direction":"SHORT","entry":100,"sl":102,"tp1":98,"tp2":96,"tp3":94}
    assert validate(x,round_trip_cost_pct=0.1)["tp3_net_r"]>0
def test_bad_target_order():
    x=example();x["tp3"]=5.15
    try:validate(x,round_trip_cost_pct=0.1)
    except ValueError:return
    assert False
def test_fee_wipes_target():
    x=example();x["tp1"]=5.066
    try:validate(x,round_trip_cost_pct=0.1)
    except ValueError:return
    assert False
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
