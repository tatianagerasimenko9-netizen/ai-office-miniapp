import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.obstacle_shadow import nearest

S={"direction":"LONG","entry":100,"sl":99}
def test_nearest_confirmed():
    levels=[{"price":103,"confirmed_ts":10,"tf":"4h"},
            {"price":101,"confirmed_ts":11,"tf":"1h"},
            {"price":100.5,"confirmed_ts":30,"tf":"1d"}]
    x=nearest(S,levels,confirm_ts=20)
    assert x["obstacle_r"]==1 and x["obstacle_tf"]=="1h"

def test_unknown_not_invented():
    x=nearest(S,[{"price":101,"tf":"1h"}],confirm_ts=20)
    assert x["obstacle_r"] is None

def test_short():
    s={"direction":"SHORT","entry":100,"sl":101}
    x=nearest(s,[{"price":98,"confirmed_ts":10,"tf":"4h"}],confirm_ts=20)
    assert x["obstacle_r"]==2

def test_wrong_side():
    x=nearest(S,[{"price":98,"confirmed_ts":10}],confirm_ts=20)
    assert x["obstacle_r"] is None

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
