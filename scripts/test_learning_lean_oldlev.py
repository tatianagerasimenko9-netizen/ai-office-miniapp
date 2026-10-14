#!/usr/bin/env python3
"""Learning: завантаження історії старого Лева тримає в пам'яті лише потрібні поля (раніше повні payload ≈34 тис. подій давали +130 МБ RSS) і дає ТОЙ САМИЙ результат."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_bridge as OB  # noqa: E402
from office2.learning import job as J  # noqa: E402
from office2.learning import trades as T  # noqa: E402

bad = 0


def check(name, ok, info=""):
    global bad
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f" :: {info}"))
    bad += 0 if ok else 1


with tempfile.TemporaryDirectory() as td:
    db = os.path.join(td, "t.db")
    os.environ["OFFICE_DB_PATH"] = db
    OB.init_office_db(db)
    plans, ress = {}, {}
    for i in range(700):          # >chunk (300): перевіряє й порційне читання
        sid = f"S{i}"
        plan = {"scenario_id": sid, "symbol": "XUSDT", "direction": "LONG" if i % 2 else "SHORT", "tf": "H1", "entry": 1.0 + i / 1000, "sl": 0.98, "tp1": 1.03 + i / 1000, "confirmed_ts": 1.79e9 + i,
                "gate": {"big": ["x" * 80] * 20}}
        res = {"scenario_id": sid, "outcome": ["STOP", "TP1", "TP2", "OPEN_TIMEOUT"][i % 4], "filled": i % 5 != 0, "rejected": i % 7 == 0, "time_to_result_sec": 100 + i, "mfe_pct": 1.5, "mae_pct": 0.5, "junk": ["z" * 60] * 5}
        plans[sid], ress[sid] = plan, res
        OB._execute(db, "INSERT INTO office_events(ts_utc,event_type,signal_id,payload_json) VALUES (?,?,?,?)", ("2026-10-01T00:00:00+00:00", "SIGNAL_PLAN", sid, json.dumps(plan)))
        OB._execute(db, "INSERT INTO office_events(ts_utc,event_type,signal_id,payload_json) VALUES (?,?,?,?)", ("2026-10-01T00:00:00+00:00", "SIGNAL_RESULT", sid, json.dumps(res)))
    ref = [t for sid in ress for t in [T.from_old_lev(plans[sid], ress[sid])] if t]            # еталон: повні payload
    got = J.load_old_lev(db)
    check("той самий результат, що й з повними payload", len(got) == len(ref) and sorted(got, key=lambda t: t["id"]) == sorted(ref, key=lambda t: t["id"]), (len(got), len(ref)))
    lean = J._last_by_scenario_lean(((json.dumps(p),) for p in plans.values()), J._PLAN_KEYS)
    check("у пам'яті лише потрібні поля плану (без gate)", all(set(v) <= set(J._PLAN_KEYS) for v in lean.values()) and "gate" not in next(iter(lean.values())))
print("ALL OK" if not bad else f"FAILED {bad}")
sys.exit(1 if bad else 0)
