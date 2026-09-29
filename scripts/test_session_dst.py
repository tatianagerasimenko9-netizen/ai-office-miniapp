#!/usr/bin/env python3
"""DST transition regression for the optional session desk clock."""
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office_session_radar import session_clock_dst

def at(month, day, hour, minute=0):
    return session_clock_dst(datetime(2026, month, day, hour, minute, tzinfo=timezone.utc))
assert "london" not in at(1, 15, 7)["active"]
assert "london" in at(1, 15, 8)["active"]
assert "london" in at(7, 15, 7)["active"]
assert "london" not in at(7, 15, 6)["active"]
assert "ny" not in at(1, 15, 12)["active"]
assert "ny" in at(1, 15, 13)["active"]
assert "ny" in at(7, 15, 12)["active"]
assert at(3, 20, 11)["overlap"] is False  # US summer time, UK still winter
assert at(3, 20, 12)["overlap"] is True
assert at(7, 15, 12)["overlap"] is True
assert at(1, 15, 12)["next"] == "ny"
assert at(1, 15, 12)["next_in_min"] == 60
assert at(7, 15, 12)["order_authorized"] is False
try:
    session_clock_dst(datetime(2026, 1, 15))
except ValueError:
    pass
else:
    raise AssertionError("naive timestamp must be rejected")
print("OK session DST: UK/US transitions, overlap, next open, no orders")

from office_session_radar import session_at_utc, session_clock

# Fixed-UTC default is unchanged for replay; dst=True follows local time.
assert session_at_utc(datetime(2026, 7, 15, 7, 30, tzinfo=timezone.utc)) == "asia"
assert session_at_utc(datetime(2026, 7, 15, 7, 30, tzinfo=timezone.utc), dst=True) == "london"
assert session_at_utc(datetime(2026, 1, 15, 7, 30, tzinfo=timezone.utc), dst=True) == "asia"
assert session_at_utc(datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc), dst=True) == "london_ny_overlap"
assert session_at_utc(datetime(2026, 7, 15, 20, 30, tzinfo=timezone.utc), dst=True) == "off_session"
summer = session_clock(datetime(2026, 7, 15, 11, 0, tzinfo=timezone.utc))
assert summer["active"] == "LONDON" and summer["next"] == "NY" and summer["next_in_min"] == 60, summer
winter = session_clock(datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc))
assert winter["next"] == "NY" and winter["next_in_min"] == 120, winter
print("OK Mini App session_clock uses DST; session_at_utc default stays fixed UTC")
