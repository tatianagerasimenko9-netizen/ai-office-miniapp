#!/usr/bin/env python3
"""Крок 7/10: аудит токенів без витоку значень."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_token_audit import audit_log_line  # noqa: E402


def main() -> int:
    os.environ["TG_BOT_TOKEN"] = "secret-value-must-not-leak"
    os.environ["NEWS_API_KEY"] = "also-secret"
    line = audit_log_line()
    if "secret-value" in line or "also-secret" in line:
        print("FAIL leaked", line)
        return 1
    if "[tokens]" not in line or "TG_BOT_TOKEN" not in line:
        print("FAIL", line)
        return 1
    src = (ROOT / "office_relay_wizard.py").read_text(encoding="utf-8")
    if "audit_log_line" not in src:
        print("FAIL not wired")
        return 1
    print("OK: test_pr_token_audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
