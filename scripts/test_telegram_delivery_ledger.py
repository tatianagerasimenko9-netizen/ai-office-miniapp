#!/usr/bin/env python3
"""Offline delivery ledger regression; temporary SQLite only, no Telegram."""
import tempfile
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from office_telegram_delivery_ledger import reserve_delivery, finish_delivery, migrate_delivery_ledger, renew_delivery, mark_delivery_uncertain


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "delivery.sqlite")
        key = "SCENARIO|BTCUSDT-H1-123|SIGNAL_ENTRY|general"
        try:
            reserve_delivery(db, key, stable=True, now=999)
            raise AssertionError("missing migration must fail closed")
        except Exception as exc:
            assert "office_telegram_delivery" in str(exc), str(exc)
        migrate_delivery_ledger(db)
        # A missing/unavailable DB must not silently authorize a Telegram send.
        bad_db = str(Path(tmp) / "missing-directory" / "delivery.sqlite")
        try:
            reserve_delivery(bad_db, "SCENARIO|FAIL_CLOSED", stable=True, now=999)
            raise AssertionError("unavailable database must fail closed")
        except (sqlite3.OperationalError, OSError):
            pass
        first = reserve_delivery(db, key, stable=True, now=1000)
        assert first, "first reservation"
        assert reserve_delivery(db, key, stable=True, now=1001) is None, "concurrent duplicate"
        assert finish_delivery(db, key, first, delivered=False, stable=True, now=1002), "failed send releases"
        retry = reserve_delivery(db, key, stable=True, now=1003)
        assert retry and retry != first, "retry after failed send"
        assert finish_delivery(db, key, retry, delivered=True, stable=True, now=1004), "commit delivered"
        assert reserve_delivery(db, key, stable=True, now=1005) is None, "restart duplicate"
        assert not finish_delivery(db, key, first, delivered=False, stable=True, now=1006), "stale token"
        transient = reserve_delivery(db, "TRAIL|BTCUSDT|100|general", now=2000)
        assert transient
        assert reserve_delivery(db, "TRAIL|BTCUSDT|100|general", now=2001) is None
        assert reserve_delivery(db, "TRAIL|BTCUSDT|100|general", now=2121), "expired lease"
        assert reserve_delivery(db, "TRAIL|BTCUSDT|100|general", now=2122) is None
        assert reserve_delivery(db, "TRAIL|BTCUSDT|100|general", now=3000), "lease expiry retry"
        concurrent_key = "SCENARIO|MANTAUSDT-H1-456|CONFIRM|general"
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(
                lambda _: reserve_delivery(db, concurrent_key, stable=True, now=4000),
                range(8),
            ))
        assert len([claim for claim in claims if claim]) == 1, "exactly one concurrent owner"
        winner = next(claim for claim in claims if claim)
        assert finish_delivery(db, concurrent_key, winner, delivered=True, stable=True, now=4001)
        assert reserve_delivery(db, concurrent_key, stable=True, now=100000) is None, "stable event survives restart"
        lease_key = "SCENARIO|BTCUSDT-H1-789|CONFIRM|general"
        owner = reserve_delivery(db, lease_key, stable=True, now=5000)
        assert owner
        assert renew_delivery(db, lease_key, owner, now=5090), "owner renews before expiry"
        assert reserve_delivery(db, lease_key, stable=True, now=5121) is None, "no lease theft"
        assert not renew_delivery(db, lease_key, "wrong-token", now=5122), "wrong owner blocked"
        assert not renew_delivery(db, lease_key, owner, now=5211), "expired lease cannot revive"
        successor = reserve_delivery(db, lease_key, stable=True, now=5211)
        assert successor and successor != owner
        assert not renew_delivery(db, lease_key, owner, now=5212), "old owner cannot renew"
        assert not finish_delivery(db, lease_key, owner, delivered=True, stable=True, now=5212), "old owner cannot commit"
        assert finish_delivery(db, lease_key, successor, delivered=True, stable=True, now=5213)
        uncertain_key = "SCENARIO|BTCUSDT-H1-999|SIGNAL_ENTRY|general"
        uncertain_owner = reserve_delivery(db, uncertain_key, stable=True, now=6000)
        assert uncertain_owner
        assert mark_delivery_uncertain(db, uncertain_key, uncertain_owner)
        assert reserve_delivery(db, uncertain_key, stable=True, now=99999999) is None
        assert not finish_delivery(db, uncertain_key, uncertain_owner, delivered=True, stable=True)
        assert not mark_delivery_uncertain(db, uncertain_key, "stale-owner")
        with sqlite3.connect(db) as conn:
            state = conn.execute(
                "SELECT state FROM office_telegram_delivery WHERE dedup_key=?",
                (uncertain_key,),
            ).fetchone()
        assert state == ("UNCERTAIN",), state
    print("OK persistent delivery ledger offline")


if __name__ == "__main__":
    main()
