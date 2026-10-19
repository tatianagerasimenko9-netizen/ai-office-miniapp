import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.structure_metrics import metrics

def bars():
    b=[{"open":100,"high":101,"low":99,"close":100,"volume":100} for _ in range(30)]
    b[21]={"open":100,"high":104,"low":100,"close":103,"volume":200}
    b[22]={"open":102,"high":103,"low":100.5,"close":102,"volume":120}
    b[23]={"open":102,"high":104,"low":101,"close":103,"volume":110}
    return b

def signal():
    return {"break_i":21,"retest_i":22,"confirm_i":23,"direction":"LONG",
            "level":101,"entry":103,"sl":100,"targets":[{"p":104},{"p":105},{"p":106}]}

def test_metrics():
    x=metrics(signal(),bars())
    assert x["breakout_volume_ratio"]==2
    assert x["retest_delay_m15_bars"]==1
    assert x["tp3_r"]==1
    assert x["mode"]=="SHADOW_ONLY"

def test_future_bars_ignored():
    b=bars()
    a=metrics(signal(),b)
    b.extend([{"open":1,"high":100000,"low":0,"close":9999,"volume":100000}])
    assert metrics(signal(),b)==a

def test_bad_indices():
    s=signal();s["confirm_i"]=21
    try:metrics(s,bars())
    except ValueError:pass
    else:raise AssertionError("invalid order accepted")

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"):fn()
    print("OK")
