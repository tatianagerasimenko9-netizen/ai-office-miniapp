import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.chart_overlay import overlay

ROW={"sig_id":"BR|ETHUSDT|SHORT|2358.57|1","symbol":"ETHUSDT",
     "direction":"SHORT","entry":2348.78,"sl":2360.39,"level":2358.57,
     "targets":[{"p":2337.17},{"p":2325.55}],"break_ts":1,"retest_ts":2,"confirm_ts":3}

def test_eth_levels_exact():
    x=overlay(ROW)
    assert [(l["id"],l["price"]) for l in x["lines"]]==[
        ("BREAKOUT",2358.57),("ENTRY",2348.78),("SL",2360.39),
        ("TP1",2337.17),("TP2",2325.55)]
    assert [p["kind"] for p in x["structure"]]==["BREAK","RETEST","CONFIRM"]

def test_reject_inverted_stop():
    try: overlay(dict(ROW,sl=2340))
    except ValueError: return
    raise AssertionError("inverted stop accepted")

def test_reject_wrong_target():
    try: overlay(dict(ROW,targets=[{"p":2360}]))
    except ValueError: return
    raise AssertionError("wrong target accepted")

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
