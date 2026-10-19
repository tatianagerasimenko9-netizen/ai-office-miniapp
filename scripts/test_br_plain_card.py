import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.plain_card import format_plan
def test_example_wait():
    x=format_plan({"symbol":"EPICUSDT","direction":"SHORT","zone":"0,2985–0,3081",
        "trigger":"0,2850","trigger_verified":False,"retest":"0,2850 знизу",
        "sl":"0,3165","tp1":"0,2700","tp2":"0,2500","decision":"WAIT"})
    assert "ПОПЕРЕДНІЙ" in x and "Рішення зараз: ЧЕКАТИ" in x
def test_no_unverified_entry():
    x=format_plan({"symbol":"EPICUSDT","direction":"SHORT","trigger":"0,2850",
                   "decision":"CONSIDER","risk_ok":True})
    assert "Рішення зараз: ЧЕКАТИ" in x
def test_no_bad_rr_entry():
    x=format_plan({"symbol":"EPICUSDT","direction":"SHORT","trigger":"0,2850",
                   "trigger_verified":True,"decision":"CONSIDER","risk_ok":False})
    assert "Рішення зараз: НЕ ВХОДИТИ" in x
def test_verified_risk():
    x=format_plan({"symbol":"EPICUSDT","direction":"SHORT","trigger":"0,2850",
                   "trigger_verified":True,"decision":"CONSIDER","risk_ok":True})
    assert "Рішення зараз: МОЖНА РОЗГЛЯНУТИ ВХІД" in x
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
