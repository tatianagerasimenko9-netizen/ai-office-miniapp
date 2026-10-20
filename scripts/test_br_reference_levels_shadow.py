import sys
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.reference_levels_shadow import reference_levels
def ts(s):return datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
def test_previous_day_only():
    a=ts("2026-10-19T13:00:00Z")
    bars=[{"ts":ts("2026-10-18T00:00:00Z"),"high":100,"low":90},
          {"ts":ts("2026-10-19T12:45:00Z"),"high":999,"low":1}]
    r=reference_levels(bars,asof_ts=a)
    assert r["PDH"]==100 and r["PDL"]==90 and not r["PD_complete"]
def test_previous_week_boundary():
    a=ts("2026-10-19T13:00:00Z")
    bars=[{"ts":ts("2026-10-12T00:00:00Z"),"high":105,"low":95},
          {"ts":ts("2026-10-18T23:45:00Z"),"high":110,"low":91}]
    r=reference_levels(bars,asof_ts=a)
    assert r["PWH"]==110 and r["PWL"]==91
def test_no_future_leak():
    a=ts("2026-10-19T13:00:00Z")
    b=[{"ts":ts("2026-10-18T00:00:00Z"),"high":100,"low":90}]
    first=reference_levels(b,asof_ts=a)
    b.append({"ts":ts("2026-10-20T00:00:00Z"),"high":999,"low":1})
    assert reference_levels(b,asof_ts=a)==first
if __name__=="__main__":
    for k,v in list(globals().items()):
        if k.startswith("test_"):v()
    print("OK")
