#!/usr/bin/env python3
"""Explicit, additive, idempotent release migration (PR #68/#69).

  python3 scripts/migrate_release.py --check            # read-only: which tables exist
  python3 scripts/migrate_release.py --apply            # create the missing tables (never alters/drops)

DB: --db URL, else DATABASE_URL, else OFFICE_DB_PATH. Secrets are never printed (fingerprint only).
Run it ONLY after a verified backup and only with the owner's approval for production.
Creates: office_telegram_delivery, office_telegram_scenario_thread, office_position_events.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TABLES = ("office_telegram_delivery", "office_telegram_scenario_thread", "office_position_events")


def resolve_db(arg: str) -> str:
    return arg or os.getenv("DATABASE_URL", "").strip() or os.getenv("OFFICE_DB_PATH", "office_bridge.db")


def present(db: str) -> dict:
    from office_bridge import _fetchone

    out = {}
    for t in TABLES:
        try:
            _fetchone(db, f"SELECT 1 FROM {t} LIMIT 1", ())
            out[t] = True
        except Exception:
            out[t] = False
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    db = resolve_db(a.db)
    from office_bridge import office_db_identity

    ident = office_db_identity(db)
    print("DB:", {k: v for k, v in ident.items() if k != "password"})
    before = present(db)
    print("BEFORE:", before)
    if a.check:
        return 0 if all(before.values()) else 2
    from office_positions import migrate_positions
    from office_telegram_delivery_ledger import migrate_delivery_ledger

    migrate_delivery_ledger(db)   # also creates office_telegram_scenario_thread
    migrate_positions(db)
    after = present(db)
    print("AFTER: ", after)
    if not all(after.values()):
        print("FAIL: some tables are still missing")
        return 1
    print("OK: migration applied (idempotent, additive)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
