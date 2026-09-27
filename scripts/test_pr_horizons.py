#!/usr/bin/env python3
"""Крок 8/10: горизонти BTC D1/H4/H1 у лог."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_horizons import horizon_log_line, horizon_pack  # noqa: E402


def main() -> int:
    empty = horizon_pack([], None, [])
    if empty.get("status") != "DATA_UNAVAILABLE":
        print("FAIL empty", empty)
        return 1
    if "DATA_UNAVAILABLE" not in horizon_log_line(empty):
        print("FAIL line")
        return 1
    ok = horizon_pack(
        [{"close": 100.0}],
        [{"close": 101.0}],
        [{"close": 102.0}],
    )
    if not ok.get("ok") or "D1=100" not in horizon_log_line(ok):
        print("FAIL ok", ok)
        return 1
    src = (ROOT / "office_relay_wizard.py").read_text(encoding="utf-8")
    if "horizon_log_line" not in src:
        print("FAIL not wired")
        return 1
    print("OK: test_pr_horizons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
