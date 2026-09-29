#!/usr/bin/env python3
"""Старі рядки trade_journal (симуляції OFFICE_SIGNAL, «Desk ENTER» тощо) не є ручними угодами:
не потрапляють у ручний журнал, у експозицію і в ризик Risk Officer. Дзеркало реальних даних production (2026-09-29)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
db = str(Path(tempfile.mkdtemp()) / "l.db")
os.environ["OFFICE_DB_PATH"] = db
os.environ["DATABASE_URL"] = ""
from office_bridge import init_office_db, _execute as _exec  # noqa: E402
import office_positions as P  # noqa: E402
from office_risk_context import existing_risk_usdt  # noqa: E402

init_office_db(db)
P.migrate_positions(db)
LEGACY = [("osig-1", "OFFICE_SIGNAL", "office signal card (not /position)"),
          ("rs-1", "relay_signal", "Desk ENTER after agent chain"),
          ("ar-1", "Asian Range", "Desk ENTER after agent chain"),
          ("js-1", "Judas Swing", "Desk ENTER after agent chain")]
for tid, setup, reason in LEGACY:
    _exec(db, "INSERT INTO trade_journal (trade_id, ts_open_utc, symbol, direction, status, entry_price, stop_loss, take_profit, "
              "position_qty, setup_name, entry_reason, mistake_tags_json, context_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (tid, "2026-09-28T00:00:00+00:00", "BTCUSDT", "LONG", "OPEN", 100.0, 90.0, 120.0, 5.0, setup, reason, "[]", "{}"))
assert P.list_positions(db, "all") == [], "legacy simulation rows must not appear as manual positions"
assert P.exposure(db)["status"] == "NONE_RECORDED"
r = existing_risk_usdt(db)
assert r["value"] == 0.0 and r["open"] == 0, r
p = P.open_position(db, symbol="ETHUSDT", direction="LONG", entry=100, qty=1, sl=95, note="TEST")
assert [x["trade_id"] for x in P.list_positions(db, "all")] == [p["trade_id"]]
assert existing_risk_usdt(db)["open"] == 1
print("OK legacy OPEN simulations are isolated from the manual ledger and risk exposure")
