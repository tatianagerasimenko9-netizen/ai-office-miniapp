#!/usr/bin/env python3
"""TTL 2.0: годинник — лише верхня межа; план знімають причини; сценарій з Азії переживає Лондон; зняття за часом перевіряється заднім числом (FALSE_EXPIRY)."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["OFFICE_DEPO_USDT"] = "1000"
os.environ["OFFICE_EXINFO_SEED"] = "1"
import office_scenario_ttl as TT  # noqa: E402
import office_scenario_lifecycle as L  # noqa: E402
import office_signal_track as T  # noqa: E402
from office_confluence import follow_setup  # noqa: E402

d = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()  # noqa: E731
hhmm = lambda x: datetime.fromtimestamp(x, tz=timezone.utc).strftime("%d %H:%M")  # noqa: E731
# межі: M15 — до кінця НАСТУПНОЇ сесії; Азія переживає Лондон; H1 24, H4 48, D1 5 діб
assert hhmm(TT.deadline(d("2026-09-30T00:30:00"), "M15")) == "30 16:00"      # створено в Азії → живе до кінця Лондона
assert hhmm(TT.deadline(d("2026-09-29T22:00:00"), "M15")) == "30 08:00"      # між сесіями → до кінця Азії
assert TT.deadline(100.0, "H1") == 100.0 + 24 * 3600 and TT.deadline(100.0, "H4") == 100.0 + 48 * 3600 and TT.deadline(100.0, "D1") == 100.0 + 5 * 86400
# AKE: створений о 22:00 UTC (H1) о 03:17 (5 год) НЕ знімається за часом
assert not TT.is_time_expired(d("2026-09-29T22:00:00"), "H1", d("2026-09-30T03:17:00"))

H = 3600.0
NOW = d("2026-09-30T12:00:00")


def c(open_ts, o, h, l, cl):
    return {"ts": datetime.fromtimestamp(open_ts, tz=timezone.utc).isoformat(), "open": o, "high": h, "low": l, "close": cl}


# структура: свінг-мінімум 100 (до створення), закриття H1 під ним після створення → злам структури (раніше за стоп 95)
born = NOW - 6 * H
pre = [c(born - (12 - i) * H, 103, 104, 103, 103.5) for i in range(12)]
pre[6] = c(born - 6 * H, 102, 103, 100.0, 101)          # свінг-мінімум
after = [c(born + i * H, 101, 102, 99, 100.5) for i in range(3)] + [c(born + 3 * H, 100.4, 100.6, 98.5, 99.0)]
assert L.structure_break_h1(pre + after, side="LONG", since_ts=born, now_ts=NOW) is not None
assert L.structure_break_h1(pre + after[:3], side="LONG", since_ts=born, now_ts=NOW) is None, "тінь без закриття — не злам"
# ціль без входу: зону 100–101 не торкались, а TP1 106 досягнуто
zone = dict(zone_lo=100.0, zone_hi=101.0, tp1=106.0)
away = [c(born + i * H, 104, 107 if i == 2 else 105, 103.5, 104.5) for i in range(4)]
assert L.target_without_entry(away, side="LONG", since_ts=born, now_ts=NOW, **zone) is True
touched_first = [c(born, 102, 102.5, 100.5, 101.5)] + away[1:]
assert L.target_without_entry(touched_first, side="LONG", since_ts=born, now_ts=NOW, **zone) is False
# follow_setup віддає причину з типом
setup = {"symbol": "XUSDT", "direction": "LONG", "sl": 95.0, "zone_lo": 100.0, "zone_hi": 101.0, "tp1": 106.0, "ts": born, "timeframe": "H1"}
fu = follow_setup(setup=setup, price=104.0, candles_ltf=[], now_ts=NOW, candles_h1=pre + away)
assert fu["action"] == "cancel" and fu["kind"] == "TARGET_NO_ENTRY", fu
fu = follow_setup(setup=setup, price=99.0, candles_ltf=[], now_ts=NOW, candles_h1=pre + after)
assert fu["action"] == "cancel" and fu["kind"] == "STRUCTURE", fu
fu = follow_setup(setup={**setup, "ts": NOW - 25 * H}, price=102.0, candles_ltf=[], now_ts=NOW, candles_h1=[])
assert fu["action"] == "cancel" and fu["kind"] == "TIME", fu
fu = follow_setup(setup={**setup, "ts": NOW - 20 * H}, price=102.0, candles_ltf=[], now_ts=NOW, candles_h1=[])
assert fu["action"] != "cancel", "20 год для H1 — ще живий"

# підтверджений план: ціна за межею входу → знято; час — лише коли причин немає
act = L.confirmed_plan_action(ts_updated=NOW - 2 * H, tf="H1", sl=95.0, direction="LONG", candles_h1=[], has_position=False, now_ts=NOW, tp1=106.0, price=105.0)
assert act and act["reason"] == "BEYOND_MAX_ENTRY", act
act = L.confirmed_plan_action(ts_updated=NOW - 30 * H, tf="H1", sl=95.0, direction="LONG", candles_h1=[], has_position=False, now_ts=NOW)
assert act and act["reason"] == "TIME"
assert L.confirmed_plan_action(ts_updated=NOW - 30 * H, tf="H1", sl=95.0, direction="LONG", candles_h1=[], has_position=True, now_ts=NOW) is None

# FALSE_EXPIRY: зняли за часом, а ціна потім зайшла в зону й дійшла до TP1 → позначка; інакше — ок; пишеться один раз
from office_bridge import init_office_db  # noqa: E402

db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
try:
    init_office_db(db)
    exp_ts = NOW - 10 * H
    T.record_expiry(db, scenario_id="SCN|AKE", symbol="AKEUSDT", direction="LONG", zone_lo=100, zone_hi=101, sl=98, tp1=104, expired_ts=exp_ts)
    T.record_expiry(db, scenario_id="SCN|BAD", symbol="BADUSDT", direction="LONG", zone_lo=100, zone_hi=101, sl=98, tp1=104, expired_ts=exp_ts)
    good = [c(exp_ts + i * 900, 100.6, 100.8, 100.4, 100.6) for i in range(2)] + [c(exp_ts + 2 * 900, 100.6, 104.5, 100.5, 104)]
    bad = [c(exp_ts + i * 900, 100.6, 100.8, 100.4, 100.6) for i in range(2)] + [c(exp_ts + 2 * 900, 100.6, 100.7, 97.5, 98)]
    fetch = lambda sym, tf, n: good if sym == "AKEUSDT" else bad  # noqa: E731
    res = {r["scenario_id"]: r["false_expiry"] for r in T.check_false_expiry(db, fetch=fetch, now_ts=NOW)}
    assert res == {"SCN|AKE": True, "SCN|BAD": False}, res
    assert T.check_false_expiry(db, fetch=fetch, now_ts=NOW) == []
    rep = T.report(db)
    assert rep["time_expiry"] == {"expired_by_time": 2, "checked": 2, "false_expiry": 1}, rep["time_expiry"]
finally:
    os.unlink(db)
print("OK TTL 2.0: reasons first, clock only as upper bound, Asia survives London, FALSE_EXPIRY checked")
