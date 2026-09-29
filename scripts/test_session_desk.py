#!/usr/bin/env python3
"""Session Desk: previous/current session ranges with DST, sweep vs acceptance. Offline."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office_session_desk import session_brief  # noqa: E402


def m15(start, prices):
    out = []
    for i, (h, l, c) in enumerate(prices):
        out.append({"ts": (start + timedelta(minutes=15 * i)).isoformat(), "high": h, "low": l, "close": c})
    return out


# Winter: London 08:00-16:00 UTC. Asia 00-08 UTC range 100-110.
day = datetime(2026, 1, 15, tzinfo=timezone.utc)
asia = m15(day, [(110 if i == 5 else 105, 100 if i == 9 else 103, 104) for i in range(32)])
# London open: spike to 112 then close back at 108 -> sweep of Asia high.
london = m15(day + timedelta(hours=8), [(112, 106, 108), (109, 107, 108), (108.5, 107, 107.5)])
b = session_brief(asia + london, now_utc=day + timedelta(hours=8, minutes=50))
assert b["data_status"] == "DATA_OK" and b["previous"]["name"] == "Азія", b
assert b["previous"]["high"] == 110 and b["previous"]["low"] == 100
assert b["since_previous"]["high_test"]["state"] == "SWEEP"
assert b["since_previous"]["low_test"]["state"] == "NOT_TESTED"
assert b["current"]["name"] == "Лондон" and b["is_signal"] is False and b["order_authorized"] is False

# Acceptance: closes above the Asia high.
acc = m15(day + timedelta(hours=8), [(112, 108, 111.5), (113, 111, 112.5), (113, 111.5, 112.8), (114, 112, 113)])
a = session_brief(asia + acc, now_utc=day + timedelta(hours=9, minutes=5))
assert a["since_previous"]["high_test"]["state"] == "ACCEPTED", a

# Summer: London opens 07:00 UTC -> at 07:30 UTC London is active (DST).
sday = datetime(2026, 7, 15, tzinfo=timezone.utc)
prev_ny = m15(sday - timedelta(hours=12), [(50, 49, 49.5)] * 32)  # 12:00-20:00 UTC = NY 08-16 EDT
s = session_brief(prev_ny + m15(sday, [(50, 49, 49.5)] * 30), now_utc=sday + timedelta(hours=7, minutes=30))
assert "Лондон" in s["active"], s["active"]

assert session_brief([], now_utc=day)["data_status"] == "DATA_UNAVAILABLE"
assert session_brief(m15(day, [(1, 2, 1)] * 10), now_utc=day + timedelta(hours=9))["data_status"] == "DATA_UNAVAILABLE"
import os
from office_mini_v2 import session_payload
assert session_payload("BTC/../x?y=1")["data_status"] == "DATA_UNAVAILABLE"
os.environ["OFFICE_MINI_FIXTURE"] = "1"
assert session_payload("BTCUSDT")["fixture"] is True
print("OK Session Desk: ranges, sweep vs acceptance, DST London open, honest unavailable")

# DST transition days and the midnight boundary (windows are recomputed from the clock each call: restart-safe).
def _active(ts):
    day = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    cands = m15(day - timedelta(days=2), [(10, 9, 9.5)] * 4 * 24 * 3)
    return session_brief(cands, now_utc=ts)["active"]

# UK clocks forward on 2026-03-29 01:00 UTC: London 08:00 local = 08:00 UTC on 03-28 but 07:00 UTC on 03-29.
assert "Лондон" not in _active(datetime(2026, 3, 28, 7, 30, tzinfo=timezone.utc))
assert "Лондон" in _active(datetime(2026, 3, 29, 7, 30, tzinfo=timezone.utc))
# US clocks forward on 2026-03-08: NY 08:00 local = 13:00 UTC on 03-06 but 12:00 UTC on 03-09.
assert "Нью-Йорк" not in _active(datetime(2026, 3, 6, 12, 30, tzinfo=timezone.utc))
assert "Нью-Йорк" in _active(datetime(2026, 3, 9, 12, 30, tzinfo=timezone.utc))
# UK clocks back on 2026-10-25: London 08:00 local = 07:00 UTC before, 08:00 UTC after.
assert "Лондон" in _active(datetime(2026, 10, 24, 7, 30, tzinfo=timezone.utc))
assert "Лондон" not in _active(datetime(2026, 10, 26, 7, 30, tzinfo=timezone.utc))
# Midnight UTC: Asia starts, previous-session range is still the last completed session.
b0 = session_brief(m15(datetime(2026, 6, 10, tzinfo=timezone.utc) - timedelta(days=2),
                       [(10, 9, 9.5)] * 4 * 24 * 3), now_utc=datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc))
assert b0["data_status"] == "DATA_OK" and "Азія" in b0["active"] and b0["previous"]["end"] <= "2026-06-10T00:00:00+00:00", b0
print("OK Session Desk DST transition days and midnight boundary")
