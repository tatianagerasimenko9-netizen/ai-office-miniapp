import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.regime_report import report

def make(i,status,asof=None,trend="LONG",obstacle=2):
    return {"created_ts":i,"feature_asof_ts":i if asof is None else asof,
      "status":status,"symbol":"ETHUSDT","direction":"LONG","entry":100,"sl":99,
      "targets":[{"p":101},{"p":102},{"p":103}],
      "htf":{"direction":trend},"obstacle":{"valid":True,"obstacle_r":obstacle}}

def test_holdout_loss_not_approved():
    rows=[make(i,"TP3" if i<20 else "SL") for i in range(40)]
    x=report(rows)
    assert x["test"]["sl"]==20 and not x["eligible_for_live_review"]
    assert not x["production_gate_changed"]

def test_future_feature_rejected():
    rows=[make(10,"TP3",asof=11),make(20,"SL")]
    x=report(rows)
    assert x["excluded_missing_or_future_features"]==1

def test_unknown_regime_excluded():
    x=report([make(i,"TP3",trend="UNKNOWN") for i in range(40)])
    assert x["test"]["n"]==0 and x["baseline"]["test"]["n"]==20

def test_near_obstacle_excluded():
    x=report([make(i,"TP3",obstacle=0.5) for i in range(40)])
    assert x["test"]["n"]==0

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
