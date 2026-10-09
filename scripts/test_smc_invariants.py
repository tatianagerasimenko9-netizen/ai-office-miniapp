#!/usr/bin/env python3
"""Інваріанти детекторів SMC: на синтетиці (CI) і, якщо задано SMC_REAL_DIR з npz (scripts/smc_real_convert.py), на РЕАЛЬНИХ біржових свічках."""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.smc import fixtures as FX  # noqa: E402
from office2.smc import invariants as INV  # noqa: E402


def test_invariants_hold_on_scheme_fixtures_and_random_walks():
    for b in (FX.uptrend(), FX.downtrend(), FX.mss_confirm(), FX.reversal_long(), FX.continuation_long(), FX.reflect(FX.reversal_long())):
        r = INV.run(b)
        assert not r["violations"], r["violations"]
    rs = np.random.RandomState(21)
    for _ in range(6):
        n = 300
        c = 100 + np.cumsum(rs.randn(n) * 0.7)
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) + np.abs(rs.randn(n)) * 0.3
        l = np.minimum(o, c) - np.abs(rs.randn(n)) * 0.3
        r = INV.run(FX.bars(list(zip(o, h, l, c))))
        assert not r["violations"], r["violations"]
        assert r["checks"] > 50


def test_real_data_if_available():
    d = os.environ.get("SMC_REAL_DIR")
    if not d:
        return
    out = {}
    for p in sorted(Path(d).glob("*.npz")):
        z = np.load(p)
        m15 = {k: z[f"m15_{k}"] for k in ("t", "o", "h", "l", "c", "v")}
        r = INV.run(m15)
        out[p.stem] = r
        assert not r["violations"], (p.stem, r["violations"])
    print("real:", {k: (v["bars"], v["checks"], len(v["violations"])) for k, v in out.items()})


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
