#!/usr/bin/env python3
"""Крок 6/10: каталог команд у лог, не в чат."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_command_catalog import COMMANDS, catalog_log_line  # noqa: E402


def main() -> int:
    line = catalog_log_line()
    if not line.startswith("[commands]"):
        print("FAIL prefix")
        return 1
    for name, _ in COMMANDS:
        token = name.split()[0]
        if token not in line:
            print(f"FAIL missing {token}")
            return 1
    src = (ROOT / "office_relay_wizard.py").read_text(encoding="utf-8")
    if "catalog_log_line" not in src:
        print("FAIL not wired")
        return 1
    print("OK: test_pr_cmd_audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
