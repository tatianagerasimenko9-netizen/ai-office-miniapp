#!/usr/bin/env python3
from office_bulkowski_kernel import BULKOWSKI_KERNEL

assert "ЯДРО БУЛКОВСКІ" in BULKOWSKI_KERNEL
assert "failure rate" not in BULKOWSKI_KERNEL.lower()
print("ok bulkowski kernel")
