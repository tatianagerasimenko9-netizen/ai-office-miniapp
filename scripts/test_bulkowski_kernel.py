#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bulkowski_kernel import BULKOWSKI_KERNEL  # noqa: E402

assert "ЯДРО БУЛКОВСКІ" in BULKOWSKI_KERNEL
assert "failure rate" not in BULKOWSKI_KERNEL.lower()
print("ok bulkowski kernel")
