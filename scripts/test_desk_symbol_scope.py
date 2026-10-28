#!/usr/bin/env python3
"""#169: desk lookups stay symbol-scoped without changing fallback semantics."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

import office_bridge as bridge  # noqa: E402
from office_desk_card import latest_open_desk_signal  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "desk.db")
        bridge.init_office_db(db)
        for sid, sym, status, note in (
            ("btc-good", "BTCUSDT", "ACTIVE", "PUMP cancel=84000"),
            ("desk-range-btc-legacy", "BTCUSDT", "ACTIVE", "old"),
            ("eth-other", "ETHUSDT", "ACTIVE", "not BTC"),
            ("btc-watch", "BTCUSDT", "WATCHING", "not an open position"),
        ):
            bridge.signal_upsert(
                db, signal_id=sid, symbol=sym, direction="LONG",
                entry_low=84069.0, entry_high=84069.0, sl=83756.0,
                tp1=84500.0, tp2=None, rr=2.0, status=status,
                analysis_note=note,
            )
        # Force deterministic newest-first ordering: skip newer legacy row.
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "UPDATE office_signals SET ts_created=? WHERE signal_id=?",
                [
                    ("2026-10-01T00:00:00Z", "btc-good"),
                    ("2026-10-02T00:00:00Z", "desk-range-btc-legacy"),
                    ("2026-10-03T00:00:00Z", "eth-other"),
                    ("2026-10-04T00:00:00Z", "btc-watch"),
                ],
            )

        bridge.journal_open_trade(
            db, trade_id="manual-sol", symbol="SOLUSDT", direction="SHORT",
            entry_price=200.0, stop_loss=210.0, take_profit=180.0,
            setup_name="manual", entry_reason=bridge.POSITION_CONFIRM_REASON,
        )
        calls = []
        original = bridge._fetchall

        def scoped(db_path, sql, params=()):
            if "FROM office_signals" in sql or "FROM trade_journal" in sql:
                assert "symbol = ?" in sql, "desk query must filter symbol in SQL"
                assert len(params) == 1, "symbol must be a bound SQL parameter"
                calls.append((sql, tuple(params)))
            return original(db_path, sql, params)

        with patch.object(bridge, "_fetchall", side_effect=scoped):
            btc = latest_open_desk_signal(db, "btcusdt")
            sol = latest_open_desk_signal(db, "SOLUSDT")
            missing = latest_open_desk_signal(db, "MISSINGUSDT")
            empty = latest_open_desk_signal(db, "")

        assert btc and btc["signal_id"] == "btc-good", btc
        assert btc["entry"] == 84069.0, btc
        assert btc["cancel_level"] == 84000.0, btc
        assert sol and sol["trade_id"] == "manual-sol" and sol["direction"] == "SHORT", sol
        assert missing is None and empty is None
        assert len(calls) == 5, calls
        assert all(p[0] in {"BTCUSDT", "SOLUSDT", "MISSINGUSDT"} for _, p in calls)
        assert not any("SELECT *" in sql for sql, _ in calls)
    print("OK: symbol-scoped desk reads, legacy exclusion, journal fallback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
