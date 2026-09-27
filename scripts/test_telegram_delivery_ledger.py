#!/usr/bin/env python3
"""Offline delivery ledger regression; temporary SQLite only, no Telegram."""
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from office_telegram_delivery_ledger import reserve_delivery, finish_delivery


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "delivery.sqlite")
        key = "SCENARIO|BTCUSDT-H1-123|SIGNAL_ENTRY|general"
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
    print("OK persistent delivery ledger offline")


if __name__ == "__main__":
    main()
