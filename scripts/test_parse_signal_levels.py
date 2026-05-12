#!/usr/bin/env python3
"""
Smoke test for _parse_signal_levels_from_text (Render Shell / CI).

From repo root on Render:
  python3 -c "import sys; sys.path.insert(0, '/opt/render/project/src'); ..."
or:
  python3 scripts/test_parse_signal_levels.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_relay_wizard import _parse_signal_levels_from_text  # noqa: E402


def main() -> int:
    tests = [
        "Entry: 0.03826–0.03860",
        "Entry: 81006–81152",
        "Entry: 0.1453–0.1474 (OTE зона)",
        "Жду повернення в зону 0.1445–0.1469",
        "Entry: 0.03826\u22120.03860",  # Unicode minus U+2212
    ]
    failed = 0
    for t in tests:
        r = _parse_signal_levels_from_text(t)
        ok = r.get("entry_low") is not None and r.get("entry_high") is not None
        if not ok:
            failed += 1
        status = "OK" if ok else "FAIL"
        preview = t if len(t) <= 55 else t[:52] + "..."
        print(f"{status}  {ascii(preview)}  ->  {r}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
