#!/usr/bin/env python3
"""Продуктивність журналу подій: індекси (event_type, id) / (event_type, ts_utc) створюються при ініціалізації БД, а гарячі цикли читають лише недавнє вікно (since_ts)."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if not cond else ""))
    if not cond:
        FAILS.append(name)


import office_bridge as OB  # noqa: E402
import office_signal_track as T  # noqa: E402

db = os.path.join(tempfile.mkdtemp(), "p.db")
OB.init_office_db(db)
con = sqlite3.connect(db)
idx = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='office_events'")}
check("індекс office_events(event_type, id)", "idx_office_events_type_id" in idx, str(idx))
check("індекс office_events(event_type, ts_utc)", "idx_office_events_type_ts" in idx, str(idx))
plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN SELECT id, ts_utc, signal_id, payload_json FROM office_events WHERE event_type = 'SIGNAL_PLAN' ORDER BY id")]
check("запит за event_type іде по індексу, не повним скануванням", any("idx_office_events_type" in x for x in plan), str(plan))
con.execute("INSERT INTO office_events(ts_utc,event_type,signal_id,payload_json) VALUES ('2026-01-01T00:00:00+00:00','SIGNAL_PLAN','old','{\"scenario_id\":\"old\"}')")
con.commit()
OB.log_event(db, "SIGNAL_PLAN", {"scenario_id": "new"}, "new")
check("без since_ts читається вся історія", len(T._events(db, "SIGNAL_PLAN")) == 2)
rec = T._events(db, "SIGNAL_PLAN", time.time() - 14 * 86400)
check("з since_ts — лише недавнє вікно", [e["p"]["scenario_id"] for e in rec] == ["new"], str(rec))
print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
