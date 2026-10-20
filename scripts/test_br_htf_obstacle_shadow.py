import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.htf_obstacle_shadow import obstacle
def ctx(px):
    return {"complete":True,"pivots_high":[{"price":px}],
            "pivots_low":[{"price":px}]}
def test_long_nearest():
    r=obstacle(100,"LONG",{"1h":ctx(105),"4h":ctx(103)})
    assert r["status"]=="FOUND" and r["price"]==103 and r["source"]=="4h"
def test_short_nearest():
    r=obstacle(100,"SHORT",{"1h":ctx(90),"4h":ctx(98)})
    assert r["status"]=="FOUND" and r["price"]==98
def test_incomplete_blocks():
    c=ctx(105);c["complete"]=False
    assert obstacle(100,"LONG",{"1h":c})["status"]=="UNKNOWN"
def test_no_opposing():
    assert obstacle(100,"LONG",{"1h":ctx(90)})["status"]=="NO_CONFIRMED_OPPOSING_LEVEL"
if __name__=="__main__":
    for n,f in list(globals().items()):
        if n.startswith("test_"):f()
    print("OK")
