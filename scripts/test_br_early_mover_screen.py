"""Closed-bar early-mover screen regression tests."""
from office_br.early_mover_screen import screen,rank

def bars():
    rows=[]
    for i in range(100):
        rows.append({"high":10.0,"low":9.0,"close":9.5,"volume":100.0})
    rows[-1]={"high":10.4,"low":9.8,"close":10.2,"volume":250.0}
    return rows

def test_watchlist_not_signal():
    s=screen("ACTUSDT",bars())
    assert s["status"]=="WATCH_RETEST"
    assert s["mode"]=="RESEARCH_ONLY"
    assert "entry" not in s

def test_no_chasing():
    x=bars()
    x[-1]["close"]=12
    assert screen("QUSDT",x)["status"]=="REJECT"
    assert "OVEREXTENDED_NO_CHASE" in screen("QUSDT",x)["reasons"]

def test_weak_volume():
    x=bars()
    x[-1]["volume"]=120
    assert "WEAK_RELATIVE_VOLUME" in screen("ACTUSDT",x)["reasons"]

def test_insufficient_data():
    assert screen("ACTUSDT",bars()[:20])["status"]=="REJECT"

def test_rank_only_watchlist():
    a=screen("ACTUSDT",bars())
    b=screen("QUSDT",bars())
    assert len(rank([a,b,{"symbol":"X","status":"REJECT"}]))==2

if __name__=="__main__":
    test_watchlist_not_signal()
    test_no_chasing()
    test_weak_volume()
    test_insufficient_data()
    test_rank_only_watchlist()
    print("OK")
