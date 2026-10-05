#!/usr/bin/env python3
"""repeat_context: інструментація «що змінилось порівняно з попередньою READY пари»; не впливає на gate (лише повертає словник)."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
import office_ready_core as RC  # noqa: E402
import office_signal_track as T  # noqa: E402
from office_bridge import init_office_db, log_event  # noqa: E402

init_office_db(db)

NOW = time.time()
# немає попередніх
c0 = RC.repeat_context(db, symbol="AAAUSDT", direction="LONG", entry=10.0, sl=9.8, now=NOW)
assert c0["has_prev"] is False and c0["n_prev_total"] == 0

gate_a = {"zone": [9.9, 10.1], "confirm": {"tags": ["ob_retest", "level_retest"]}}
T.record_plan(db, scenario_id="SCN|AAA|LONG|H1|1", symbol="AAAUSDT", direction="LONG", tf="H1", entry=10.0, sl=9.8, tp1=10.6, confirmed_ts=NOW - 7200,
              valid_until_ts=NOW + 80000, rejected=False, confirm_msg_id=1, gate=gate_a)
# попередня ще без результату
c1 = RC.repeat_context(db, symbol="AAAUSDT", direction="LONG", entry=10.0, sl=9.8, tags=["ob_retest", "level_retest"], zone=[9.95, 10.05], now=NOW)
assert c1["has_prev"] and c1["prev_state"] == "unresolved" and c1["sl_diff_pct"] == 0.0 and c1["zone_overlap"] is True and c1["same_tags"] is True, c1
# ENTRY у lifecycle → open
log_event(db, T.EV_MILESTONE, {"scenario_id": "SCN|AAA|LONG|H1|1", "confirmed_ts": NOW - 7200, "level": "ENTRY", "touched_ts": NOW - 6000}, "SCN|AAA|LONG|H1|1")
assert RC.repeat_context(db, symbol="AAAUSDT", direction="LONG", entry=10.0, sl=9.8, now=NOW)["prev_state"] == "open"
# SL у lifecycle → sl, час від SL
log_event(db, T.EV_MILESTONE, {"scenario_id": "SCN|AAA|LONG|H1|1", "confirmed_ts": NOW - 7200, "level": "SL", "touched_ts": NOW - 3600}, "SCN|AAA|LONG|H1|1")
c2 = RC.repeat_context(db, symbol="AAAUSDT", direction="LONG", entry=10.2, sl=9.9, tags=["fvg"], zone=[10.5, 10.6], now=NOW)
assert c2["prev_state"] == "sl" and 59 <= c2["since_prev_sl_min"] <= 61 and c2["zone_overlap"] is False and c2["same_tags"] is False and c2["sl_diff_pct"] > 0.9, c2
# інший напрямок і інший символ не рахуються; відхилений план не рахується
assert not RC.repeat_context(db, symbol="AAAUSDT", direction="SHORT", entry=10.0, sl=10.2, now=NOW)["has_prev"]
assert not RC.repeat_context(db, symbol="BBBUSDT", direction="LONG", entry=10.0, sl=9.8, now=NOW)["has_prev"]
T.record_plan(db, scenario_id="SCN|CCC|LONG|H1|1", symbol="CCCUSDT", direction="LONG", tf="H1", entry=5.0, sl=4.9, tp1=5.3, confirmed_ts=NOW - 100, valid_until_ts=NOW + 1000, rejected=True, reason="x")
assert not RC.repeat_context(db, symbol="CCCUSDT", direction="LONG", entry=5.0, sl=4.9, now=NOW)["has_prev"]
# результат 15m STOP без lifecycle → sl за ct+time_to_result
T.record_plan(db, scenario_id="SCN|DDD|SHORT|H1|1", symbol="DDDUSDT", direction="SHORT", tf="H1", entry=5.0, sl=5.1, tp1=4.7, confirmed_ts=NOW - 5400, valid_until_ts=NOW + 1000, rejected=False, confirm_msg_id=2)
log_event(db, T.EV_RESULT, {"scenario_id": "SCN|DDD|SHORT|H1|1", "confirmed_ts": NOW - 5400, "outcome": "STOP", "time_to_result_sec": 1800}, "SCN|DDD|SHORT|H1|1")
c3 = RC.repeat_context(db, symbol="DDDUSDT", direction="SHORT", entry=5.0, sl=5.1, now=NOW)
assert c3["prev_state"] == "sl" and 59 <= c3["since_prev_sl_min"] <= 61, c3
print("OK")
