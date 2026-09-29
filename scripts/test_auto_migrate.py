#!/usr/bin/env python3
"""OFFICE_AUTO_MIGRATE: за замовчуванням вимкнено; коли ввімкнено — створює лише нові таблиці, ідемпотентно, без втрати даних."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
db = str(Path(tempfile.mkdtemp()) / "m.db")
os.environ["OFFICE_DB_PATH"] = db
os.environ["DATABASE_URL"] = ""
import office_mini_app as A  # noqa: E402
from office_bridge import init_office_db, log_event, _fetchone  # noqa: E402

init_office_db(db)
log_event(db, "KEEP_ME", {"x": 1}, "s1")
os.environ.pop("OFFICE_AUTO_MIGRATE", None)
assert A.auto_migrate_if_enabled(db) == "disabled"
import office_positions as P  # noqa: E402
assert not P.schema_present(db)
os.environ["OFFICE_AUTO_MIGRATE"] = "1"
assert A.auto_migrate_if_enabled(db) == "applied"
assert A.auto_migrate_if_enabled(db) == "applied"  # повторний запуск безпечний
assert P.schema_present(db)
for t in ("office_telegram_delivery", "office_telegram_scenario_thread", "office_position_events"):
    _fetchone(db, f"SELECT 1 FROM {t} LIMIT 1", ())
assert _fetchone(db, "SELECT COUNT(*) FROM office_events WHERE event_type='KEEP_ME'", ())[0] == 1
print("OK auto-migrate: default off; additive, idempotent, existing data intact")
