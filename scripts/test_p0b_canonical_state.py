#!/usr/bin/env python3
"""P0b: один канонічний стан READY для Telegram і Mini App (SIGNAL_PLAN), цілі/строк із знімка, перевірка новин з того ж календаря. Офлайн."""
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = str(Path(tempfile.mkdtemp()) / "c.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1", OFFICE_CALENDAR_BLOCK="1")
import office_calendar as cal  # noqa: E402
import office_execution_check as EX  # noqa: E402
import office_ready_core as RC  # noqa: E402
import office_scenario_state as SS  # noqa: E402
import office_signal_track as T  # noqa: E402
from office_bridge import init_office_db  # noqa: E402

init_office_db(db)
NOW = time.time()
SID = "SCN|ABCUSDT|SHORT|H1|1111"
row = {"signal_id": SID, "symbol": "ABCUSDT", "direction": "SHORT", "entry_low": 0.1326, "entry_high": 0.1356, "sl": 0.1362, "tp1": 0.12727, "tp2": 0.12321,
       "status": "CONFIRMED", "ts_created": datetime.now(timezone.utc).isoformat(), "ts_updated": datetime.now(timezone.utc).isoformat(),
       "analysis_note": f"ЛЕВ cancel=0.136198 ckey=x origin=desk tf=H1 scenario_id={SID} confirm_sent=1 confirmed_px=0.1328"}
thesis = {"state": "WATCHING", "confirmation": [], "invalidation": "закриття за 0.136198"}   # застаріла теза без умови (випадок OP)
price = {"price": 0.13277, "fresh": True, "as_of": datetime.now(timezone.utc).isoformat()}
ok_check = lambda *a, **k: None  # noqa: E731

# без знімка плану — як раніше: умови підтвердження не записано → НЕ готово
v0 = SS.build(row, thesis=thesis, price=price, plan_check=ok_check)
assert v0["state"] == "NOT_READY" and any("умову підтвердження" in m for m in v0["missing"]), v0
# знімок є (доставлений READY) → той самий стан, що й у Telegram; цілі й строк — із знімка
T.record_plan(db, scenario_id=SID, symbol="ABCUSDT", direction="SHORT", tf="H1", entry=0.1328, sl=0.136198, tp1=0.12727, tp2=0.12321, tp3=0.12004,
              max_entry=0.131866, confirmed_ts=NOW, valid_until_ts=NOW + 86400, confirm_msg_id=777,
              gate=RC.gate_snapshot(direction="SHORT", entry=0.1328, sl=0.136198, tp1=0.12727, tp2=0.12321, tp3=0.12004,
                                    confirm=RC.confirm_basis({"confirms": ["pin_bar"], "detail": "пін-бар + закриття в зоні", "price": 0.1328, "need_retest": False})))
plan = T.plan_for(db, SID)
assert plan and plan["confirm_msg_id"] == 777 and plan["gate"]["confirm"]["tags"] == ["pin_bar"] and plan["gate"]["confirm"]["mode"] == "inside_zone"
v1 = SS.build(row, thesis=thesis, price=price, plan_check=ok_check, plan=plan)
assert v1["state"] == "READY" and not v1["missing"], v1
pl = v1["plan"]
assert "0,12321" in pl["tp2"] and "0,12004" in pl["tp3"] and "0,1328" in pl["entry"], pl
assert RC.kyiv_stamp(plan["valid_until_ts"]) in pl["valid_until"], pl["valid_until"]
# відхилений/нелоставлений план каноном не є
T.record_plan(db, scenario_id="SCN|REJ|LONG|H1|2", symbol="REJUSDT", direction="LONG", tf="H1", entry=1, sl=0.9, tp1=1.1, confirmed_ts=NOW, valid_until_ts=NOW + 1, rejected=True)
T.record_plan(db, scenario_id="SCN|UND|LONG|H1|3", symbol="UNDUSDT", direction="LONG", tf="H1", entry=1, sl=0.9, tp1=1.1, confirmed_ts=NOW, valid_until_ts=NOW + 1, confirm_msg_id=None)
assert T.plan_for(db, "SCN|REJ|LONG|H1|2") is None and T.plan_for(db, "SCN|UND|LONG|H1|3") is None
# статус не CONFIRMED (скасовано/прострочено) → знімок стан READY не повертає
v2 = SS.build({**row, "status": "EXPIRED"}, thesis=thesis, price=price, plan_check=ok_check, plan=plan)
assert v2["state"] == "EXPIRED", v2["state"]
# ціна за межею входу → неактуально, навіть із знімком
v3 = SS.build(row, thesis=thesis, price={**price, "price": 0.1300}, plan_check=ok_check, plan=plan)
assert v3["state"] == "NOT_READY" and any("межею входу" in m for m in v3["missing"]), v3

# новини: перевірка перед входом береться з того ж календаря, що й статус джерела
cal.set_events_for_tests(cal.parse([]), at=NOW)
st, det = cal.news_check(NOW)
assert st == "OK" and "немає" in det, (st, det)
ev = [{"title": "Core CPI m/m", "country": "USD", "date": datetime.fromtimestamp(NOW + 600, tz=timezone.utc).isoformat(), "impact": "High"}]
cal.set_events_for_tests(cal.parse(ev), at=NOW)
st2, det2 = cal.news_check(NOW)
assert st2 == "FAIL" and "нові плани не відкриваємо" in det2, (st2, det2)
cal.set_events_for_tests(None)
chk = lambda news: [c for c in EX.execution_checks(symbol="ABCUSDT", direction="SHORT", zone_lo=0.1326, zone_hi=0.1356, sl=0.1362, tp1=0.12727, price=0.1328, price_fresh=True,  # noqa: E731
                                                  has_open_position=False, min_rr=1.5, min_tp1_pct=3.0, news=news)["checks"] if c["key"] == "news"][0]
assert chk(None)["state"] == "UNAVAILABLE" and chk(("OK", "x"))["state"] == "OK" and chk(("FAIL", "y"))["state"] == "FAIL"
v = EX.execution_checks(symbol="ABCUSDT", direction="SHORT", zone_lo=0.1326, zone_hi=0.1356, sl=0.1362, tp1=0.12727, price=0.1328, price_fresh=True,
                        has_open_position=False, min_rr=1.5, min_tp1_pct=3.0, news=("FAIL", "новина"))
assert v["verdict"] == "BLOCKED"
print("test_p0b_canonical_state: OK")
