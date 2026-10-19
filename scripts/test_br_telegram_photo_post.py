import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.telegram_photo_post import build_photo_post
def plan():
    return {"symbol":"NEARUSDT","direction":"LONG","verified":True,
      "risk_ok":True,"confirmation":"Пробій і ретест M5 підтверджені",
      "entry":5.065,"sl":4.996,"tp1":5.145,"tp2":5.198,"tp3":5.391,
      "expires":"17:30 (Київ)","invalidation":"M15 нижче 5,011"}
def make(p=None,**kw):
    return build_photo_post(p or plan(),chart_bytes=b"PNG-fixture",
        scenario_url="https://example.org/scenario/44",
        round_trip_cost_pct=0.02,**kw)
def test_photo_caption_and_miniapp():
    x=make()
    assert x["photo"]==b"PNG-fixture"
    assert x["reply_markup"]["inline_keyboard"][0][0]["text"]=="📊 Сценарій"
    assert "ГОТОВО" in x["caption"] and "READY" not in x["caption"]
    assert "1:1,01" not in x["caption"]
def test_risk_gate():
    try:make(min_net_rr_tp1=2)
    except ValueError:return
    assert False
def test_unverified():
    p=plan();p["verified"]=False
    try:make(p)
    except ValueError:return
    assert False
def test_private_link():
    try:build_photo_post(plan(),chart_bytes=b"x",scenario_url="https://192.168.1.1/scenario",
        round_trip_cost_pct=0.02)
    except ValueError:return
    assert False
def test_invalid_link():
    try:build_photo_post(plan(),chart_bytes=b"x",scenario_url="http://example.org",
        round_trip_cost_pct=0.02)
    except ValueError:return
    assert False
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
