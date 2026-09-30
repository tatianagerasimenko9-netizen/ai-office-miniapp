#!/usr/bin/env python3
"""Сесії з DST і маніпуляційні вікна: Лондон/Нью-Йорк за місцевим часом; різні дати переходу в Європі й США; підтвердження не приймаємо перед відкриттям."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
import office_sessions as S  # noqa: E402
from office_confluence import follow_setup  # noqa: E402

u = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()  # noqa: E731
hm = lambda x: datetime.fromtimestamp(x, tz=timezone.utc).strftime("%m-%d %H:%M")  # noqa: E731


def sess(day):
    return {n: (hm(a.timestamp()), hm(b.timestamp())) for n, a, b in S.intervals_utc(datetime.fromisoformat(day).date())}


# літо (BST + EDT): Лондон 07:00–15:00 UTC, Нью-Йорк 12:00–20:00 UTC
s = sess("2026-07-15")
assert s["LONDON"] == ("07-15 07:00", "07-15 15:00") and s["NY"] == ("07-15 12:00", "07-15 20:00") and s["ASIA"] == ("07-15 00:00", "07-15 08:00"), s
# зима: Лондон 08:00–16:00 UTC, Нью-Йорк 13:00–21:00 UTC
w = sess("2026-12-10")
assert w["LONDON"] == ("12-10 08:00", "12-10 16:00") and w["NY"] == ("12-10 13:00", "12-10 21:00"), w
# між датами переходу: Європа переходить 25.10.2026, США — 01.11.2026 → 28.10: Лондон зимовий, Нью-Йорк ще літній
m = sess("2026-10-28")
assert m["LONDON"][0] == "10-28 08:00" and m["NY"][0] == "10-28 12:00", m
# навесні: США 08.03.2026, Європа 29.03.2026 → 15.03: Лондон ще зимовий, Нью-Йорк уже літній
sp = sess("2026-03-15")
assert sp["LONDON"][0] == "03-15 08:00" and sp["NY"][0] == "03-15 12:00", sp
# активні сесії й маніпуляційне вікно (30 хв ДО відкриття)
assert S.active_sessions(u("2026-07-15T13:00:00")) == ["LONDON", "NY"]
assert S.manipulation_window(u("2026-07-15T06:40:00")) == "LONDON"
assert S.manipulation_window(u("2026-07-15T11:45:00")) == "NY"
assert S.manipulation_window(u("2026-12-10T12:45:00")) == "NY" and S.manipulation_window(u("2026-12-10T06:45:00")) is None, "взимку Лондон відкривається о 08:00 UTC"
assert S.manipulation_window(u("2026-07-15T09:00:00")) is None
# підтвердження в маніпуляційному вікні не приймається; поза вікном — працює як раніше
setup = {"symbol": "XUSDT", "direction": "LONG", "sl": 95.0, "zone_lo": 100.0, "zone_hi": 101.0, "tp1": 106.0, "ts": u("2026-07-15T03:00:00"), "timeframe": "M15"}
fu = follow_setup(setup=setup, price=100.5, candles_ltf=[], now_ts=u("2026-07-15T06:50:00"))
assert fu["action"] == "hold" and fu.get("manipulation_window") == "LONDON", fu
fu = follow_setup(setup=setup, price=100.5, candles_ltf=[], now_ts=u("2026-07-15T09:00:00"))
assert not fu.get("manipulation_window"), fu
os.environ["OFFICE_MANIP_HOLD"] = "0"
assert not follow_setup(setup=setup, price=100.5, candles_ltf=[], now_ts=u("2026-07-15T06:50:00")).get("manipulation_window")
print("OK sessions: DST for London/NY (different transition dates), manipulation windows hold confirmations")
