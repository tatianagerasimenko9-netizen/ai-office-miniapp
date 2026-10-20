import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.telegram_caption import caption
def base():
    return dict(number=44,symbol="NEARUSDT",direction="LONG",verified=True,
        risk_ok=True,chart_ready=True,confirmation="M5 пробій і ретест підтверджені",
        entry="5,03–5,065",sl="4,996",tp1="5,135",tp2="5,198",
        tp3="5,391",rr_tp1="1:1,01",expires="17:30 (Київ)",
        invalidation="закриття M15 нижче 5,011")
def test_caption_ukrainian():
    x=caption(base())
    assert "ГОТОВО" in x and "READY" not in x and "5,03–5,065" in x
    assert "Можна" not in x or "МОЖНА РОЗГЛЯНУТИ ВХІД" in x
def test_no_unverified():
    p=base();p["verified"]=False
    try:caption(p)
    except ValueError:return
    assert False
def test_no_chart():
    p=base();p["chart_ready"]=False
    try:caption(p)
    except ValueError:return
    assert False
def test_no_risk():
    p=base();p["risk_ok"]=False
    try:caption(p)
    except ValueError:return
    assert False
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
