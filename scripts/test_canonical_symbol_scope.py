#!/usr/bin/env python3
"""#169: symbol-scoped canonical SQL reads preserve unfiltered callers and cache isolation."""
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
from office_thesis_journal import canonical_scenario_id  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "scenarios.db")
        bridge.init_office_db(db)
        for sid, sym, note in (
            ("btc-old", "BTCUSDT", "scenario_id=SCN|BTCUSDT|LONG|H1|old"),
            ("eth-new", "ETHUSDT", "scenario_id=SCN|ETHUSDT|LONG|H1|new"),
            ("btc-new", "BTCUSDT", "scenario_id=SCN|BTCUSDT|LONG|H1|new"),
            ("btc-nonscenario", "BTCUSDT", "not a canonical scenario"),
        ):
            bridge.signal_upsert(
                db, signal_id=sid, symbol=sym, direction="LONG",
                entry_low=10.0, entry_high=11.0, sl=9.0,
                tp1=12.0, tp2=None, rr=2.0, status="WATCHING",
                analysis_note=note,
            )
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "UPDATE office_signals SET ts_updated=? WHERE signal_id=?",
                [
                    ("2026-10-01T00:00:00Z", "btc-old"),
                    ("2026-10-03T00:00:00Z", "eth-new"),
                    ("2026-10-02T00:00:00Z", "btc-new"),
                ],
            )
        bridge._sig_cache_clear()
        calls = []
        original = bridge._fetchall

        def check_query(db_path, sql, params=()):
            if "FROM office_signals" in sql:
                calls.append((sql, tuple(params)))
                if params:
                    assert "AND symbol = ?" in sql, sql
                    assert params == ("BTCUSDT",), params
            return original(db_path, sql, params)

        with patch.object(bridge, "_fetchall", side_effect=check_query):
            scoped = bridge.signal_get_scenarios(db, symbol=" btcusdt ")
            unfiltered = bridge.signal_get_scenarios(db)
            scoped_again = bridge.signal_get_scenarios(db, symbol="BTCUSDT")

        assert [r["signal_id"] for r in scoped] == ["btc-new", "btc-old"], scoped
        assert [r["signal_id"] for r in unfiltered] == ["eth-new", "btc-new", "btc-old"], unfiltered
        assert scoped_again == scoped
        assert len(calls) == 2, calls  # separate cache keys; repeated scoped call cached

        with patch.object(bridge, "signal_get_scenarios", wraps=bridge.signal_get_scenarios) as spy:
            canonical_scenario_id(db, {
                "draft": {
                    "symbol": "BTCUSDT", "direction": "LONG", "timeframe": "H1",
                    "zone_lo": 10.0, "zone_hi": 11.0,
                    "confluence": {"market_basis": "regression"},
                }
            })
            assert spy.call_args is not None, "canonical lookup was not attempted"
            assert spy.call_args.kwargs.get("symbol") == "BTCUSDT", spy.call_args
    print("OK: symbol SQL filter, canonical caller, cache separation, full-read ordering")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
