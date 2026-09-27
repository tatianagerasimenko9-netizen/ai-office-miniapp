#!/usr/bin/env python3
"""Крок 9/10: Булковскі kernel у лог, не в SIGNAL."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bulkowski_log import bulk_log_line  # noqa: E402
from office_telegram_policy import EVENT_SIGNAL_ENTRY, may_send_proactive  # noqa: E402


def main() -> int:
    line = bulk_log_line()
    if "[bulk]" not in line or "DATA_UNAVAILABLE" == line:
        print("FAIL", line)
        return 1
    if "failure rate" in line.lower():
        print("FAIL rates")
        return 1
    src = (ROOT / "office_relay_wizard.py").read_text(encoding="utf-8")
    if "bulk_log_line" not in src:
        print("FAIL not wired")
        return 1
    if not may_send_proactive(EVENT_SIGNAL_ENTRY):
        print("FAIL quiet policy")
        return 1
    print("OK: test_pr_bulkowski_log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
