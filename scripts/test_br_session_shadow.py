import sys
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.session_shadow import sessions_at,closed_session_range
def ts(s):return datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
def test_london_dst():
    assert "LONDON" in sessions_at(ts("2026-01-19T09:00:00Z"))
    assert "LONDON" in sessions_at(ts("2026-07-20T08:00:00Z"))
    assert "LONDON" not in sessions_at(ts("2026-01-19T07:30:00Z"))
def test_new_york_dst():
    assert "NEW_YORK" in sessions_at(ts("2026-01-19T15:00:00Z"))
    assert "NEW_YORK" in sessions_at(ts("2026-07-20T14:00:00Z"))
    assert "NEW_YORK" not in sessions_at(ts("2026-01-19T14:00:00Z"))
def test_closed_bars_only():
    b=[{"ts":ts("2026-07-20T07:00:00Z"),"high":101,"low":99},
       {"ts":ts("2026-07-20T07:15:00Z"),"high":10000,"low":0}]
    r=closed_session_range(b,asof_ts=ts("2026-07-20T07:20:00Z"),name="LONDON")
    assert r["closed_bars"]==1 and r["high"]==101 and r["low"]==99
def test_no_future_leak():
    b=[{"ts":ts("2026-07-20T07:00:00Z"),"high":101,"low":99}]
    now=ts("2026-07-20T07:30:00Z")
    a=closed_session_range(b,asof_ts=now,name="LONDON")
    b.append({"ts":ts("2026-07-20T07:30:00Z"),"high":10000,"low":0})
    assert closed_session_range(b,asof_ts=now,name="LONDON")==a
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
