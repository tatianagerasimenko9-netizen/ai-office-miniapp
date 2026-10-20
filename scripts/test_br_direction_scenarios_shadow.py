import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.direction_scenarios_shadow import evaluate

def market(direction="LONG", price=120):
    return {"mode":"SHADOW_ONLY","health":{"1d":"OK","4h":"OK","1h":"OK"},
            "trend":{"direction":direction},
            "liquidity":{tf:{"complete":True,"pivots_high":[{"price":price}],
                              "pivots_low":[{"price":80}]} for tf in ("1d","4h","1h")}}

def test_long_with_obstacle():
    x=evaluate(market(),"LONG",100,95)
    assert x["scenario"]=="LONG" and x["gross_rr_to_obstacle"]==4

def test_short_with_obstacle():
    x=evaluate(market("SHORT"),"SHORT",100,105)
    assert x["scenario"]=="SHORT" and x["nearest_liquidity"]==80

def test_mixed_is_neutral():
    assert evaluate(market("MIXED"),"LONG",100,95)["scenario"]=="NEUTRAL"

def test_invalid_stop_is_neutral():
    assert evaluate(market(),"LONG",100,105)["scenario"]=="NEUTRAL"

def test_unknown_is_neutral():
    x=market()
    x["health"]["4h"]="UNKNOWN"
    assert evaluate(x,"LONG",100,95)["scenario"]=="NEUTRAL"

def test_no_confirmed_liquidity_is_neutral():
    x=market()
    for v in x["liquidity"].values(): v["pivots_high"]=[]
    assert evaluate(x,"LONG",100,95)["scenario"]=="NEUTRAL"

if __name__=="__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
