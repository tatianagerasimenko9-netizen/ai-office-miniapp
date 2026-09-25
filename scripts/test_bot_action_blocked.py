#!/usr/bin/env python3
"""T5: bot_action=BLOCKED зупиняє ENTER; інші значення — ні."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bridge import init_office_db  # noqa: E402
from office_market_state import (  # noqa: E402
    market_state_get,
    market_state_upsert,
    scanner_blocked_notice,
    scanner_signal_blocked,
)


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if scanner_signal_blocked("BLOCKED") is not True:
        return _fail("BLOCKED")
    if scanner_signal_blocked("blocked") is not True:
        return _fail("blocked case")
    for v in (None, "", "ACCEPT", "IGNORE_SOURCE", "WATCH", "NO_TRADE"):
        if scanner_signal_blocked(v):
            return _fail(f"must not block {v!r}")

    db = str(Path(tempfile.mkdtemp()) / "t5.db")
    init_office_db(db)
    if scanner_signal_blocked((market_state_get(db, "ETHUSDT") or {}).get("bot_action")):
        return _fail("missing row must not block")

    market_state_upsert(db, "ETHUSDT", bot_action="BLOCKED", office_decision="NO_TRADE")
    st = market_state_get(db, "ETHUSDT") or {}
    if not scanner_signal_blocked(st.get("bot_action")):
        return _fail("row BLOCKED")

    market_state_upsert(db, "ETHUSDT", bot_action="ACCEPT")
    st2 = market_state_get(db, "ETHUSDT") or {}
    if scanner_signal_blocked(st2.get("bot_action")):
        return _fail("ACCEPT must not block")

    note = scanner_blocked_notice("ethusdt")
    if "BLOCKED" not in note or "ETHUSDT" not in note:
        return _fail("notice")
    if "не запускаємо" not in note:
        return _fail("must say no ENTER")
    if "входь" in note.lower():
        return _fail("no vkhody")

    print("OK: test_bot_action_blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
