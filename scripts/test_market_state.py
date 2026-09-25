#!/usr/bin/env python3
"""T4: market_state upsert/get. Офлайн SQLite, без мережі."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bridge import init_office_db  # noqa: E402
from office_market_state import market_state_get, market_state_upsert  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    db = str(Path(tempfile.mkdtemp()) / "t4.db")
    init_office_db(db)
    if market_state_get(db, "BTCUSDT") is not None:
        return _fail("empty get")

    row = market_state_upsert(
        db,
        "btcusdt",
        regime="RANGE",
        watch=[{"kind": "BSL", "low": 83000, "high": 83500, "tf": "1h"}],
        event="ZONE",
        office_decision="NO_TRADE",
        bot_action="BLOCKED",
        data_quality="OK",
    )
    if row["symbol"] != "BTCUSDT":
        return _fail("symbol norm")
    if row["regime"] != "RANGE" or row["bot_action"] != "BLOCKED":
        return _fail("insert fields")
    if row["office_decision"] != "NO_TRADE":
        return _fail("decision")
    if not row["watch"] or row["watch"][0]["kind"] != "BSL":
        return _fail("watch json")

    got = market_state_get(db, "BTCUSDT")
    if not got or got["event"] != "ZONE":
        return _fail("get after insert")

    # Частковий upsert: event змінюється, regime лишається.
    row2 = market_state_upsert(db, "BTCUSDT", event="SWEEP")
    if row2["event"] != "SWEEP" or row2["regime"] != "RANGE":
        return _fail("partial upsert")
    if row2["bot_action"] != "BLOCKED":
        return _fail("bot_action preserved")

    try:
        market_state_upsert(db, "ETHUSDT", bot_action="NOPE")
        return _fail("invalid bot_action must raise")
    except ValueError:
        pass

    print("OK: test_market_state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
