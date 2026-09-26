#!/usr/bin/env python3
"""Hotfix: cloud не падає з EOFError/exit 1; OFFICE_DEPO_USDT=1000."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_position_size import depo_usdt, plan_position_size  # noqa: E402
from office_relay_wizard import _prompt  # noqa: E402
from office_telegram_policy import EVENT_SIGNAL_ENTRY, may_send_proactive  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    src = (ROOT / "office_relay_wizard.py").read_text(encoding="utf-8")
    if "await client.run_until_disconnected()\n        raise" in src:
        return _fail("disconnect must not raise process exit")
    if "process stays up" not in src:
        return _fail("need reconnect loop")
    if "cloud mode: prompts disabled" not in src:
        return _fail("need cloud prompt disable")
    if not may_send_proactive(EVENT_SIGNAL_ENTRY):
        return _fail("quiet policy")

    os.environ["OFFICE_DEPO_USDT"] = "=1000"
    if depo_usdt() != 1000.0:
        return _fail(f"depo parse {depo_usdt()}")
    sized = plan_position_size(entry=17.46, sl=17.6184, score=10, min_score=10)
    if sized.get("size_usdt") is None:
        return _fail(f"size should use depo, got {sized}")
    print(f"OK size {sized.get('line')}")
    os.environ.pop("OFFICE_DEPO_USDT", None)

    old_in, old_tty = sys.stdin, getattr(sys.stdin, "isatty", lambda: True)
    try:
        sys.stdin = io.StringIO("")
        sys.stdin.isatty = lambda: False  # type: ignore[method-assign]
        v = _prompt("NEWS_API_KEY:", default="skip")
        if v != "skip":
            return _fail(f"no-tty prompt {v!r}")
        sys.stdin = io.StringIO("")
        sys.stdin.isatty = lambda: True  # type: ignore[method-assign]
        v2 = _prompt("x:", default="eof")
        if v2 != "eof":
            return _fail(f"EOF prompt {v2!r}")
    finally:
        sys.stdin = old_in
    print("OK _prompt no TTY / EOF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
