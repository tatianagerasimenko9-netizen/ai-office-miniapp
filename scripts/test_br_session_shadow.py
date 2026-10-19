import sys
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.session_shadow import sessions_at,closed_session_range,pre_session_range
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
def test_pre_session_complete():
    b=[{"ts":ts(f"2026-07-20T06:{m:02d}:00Z"),"high":100+m,"low":90-m}
       for m in (0,15,30,45)]
    r=pre_session_range(b,asof_ts=ts("2026-07-20T07:10:00Z"),name="LONDON")
    assert r["complete"] and r["high"]==145 and r["low"]==45
    assert not pre_session_range(b[:-1],asof_ts=ts("2026-07-20T07:10:00Z"),name="LONDON")["complete"]
    assert pre_session_range(b[:-1],asof_ts=ts("2026-07-20T07:10:00Z"),name="LONDON")["high"] is None
def test_pre_session_future_bar():
    b=[{"ts":ts(f"2026-07-20T06:{m:02d}:00Z"),"high":100,"low":90} for m in (0,15,30,45)]
    assert not pre_session_range(b,asof_ts=ts("2026-07-20T06:50:00Z"),name="LONDON")["complete"]
def test_pre_session_duplicate_blocks():
    b=[{"ts":ts(f"2026-07-20T06:{m:02d}:00Z"),"high":100,"low":90}
       for m in (0,15,30,45)]
    b.append(dict(b[0]))
    r=pre_session_range(b,asof_ts=ts("2026-07-20T07:10:00Z"),name="LONDON")
    assert not r["complete"] and r["high"] is None
def test_pre_session_bad_ohlc_blocks():
    b=[{"ts":ts(f"2026-07-20T06:{m:02d}:00Z"),"high":100,"low":90}
       for m in (0,15,30,45)]
    b[0]["low"]=101
    assert not pre_session_range(b,asof_ts=ts("2026-07-20T07:10:00Z"),name="LONDON")["complete"]
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
