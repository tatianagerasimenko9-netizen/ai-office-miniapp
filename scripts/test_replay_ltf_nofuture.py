#!/usr/bin/env python3
"""Replay: M5/M1 для Brain обрізаються до барів, ЗАКРИТИХ до now (без майбутнього); td-поля потрапляють у події."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.smc import replay as RP  # noqa: E402


def arr(t0, n, w):
    t = t0 + np.arange(n) * w
    c = 100 + np.arange(n) * 0.01
    return {"t": t.astype(float), "o": c, "h": c + 0.1, "l": c - 0.1, "c": c, "v": np.ones(n)}


def main():
    a = arr(1_000_000.0, 400, 300.0)
    now = 1_000_000.0 + 200 * 300.0 + 120.0          # посеред бару №200 (він ще не закрився)
    c = RP._cut_ltf(a, 300.0, now, 60)
    assert c is not None and len(c["t"]) == 60
    assert float(c["t"][-1]) + 300.0 <= now, "в зріз потрапив незакритий бар"
    assert float(c["t"][-1]) == 1_000_000.0 + 199 * 300.0
    now2 = 1_000_000.0 + 200 * 300.0                 # рівно закриття бару №199
    c2 = RP._cut_ltf(a, 300.0, now2, 60)
    assert float(c2["t"][-1]) == 1_000_000.0 + 199 * 300.0
    assert RP._cut_ltf(a, 300.0, 1_000_000.0 + 3 * 300.0, 60) is None
    assert RP._cut_ltf(None, 300.0, now, 60) is None
    assert RP._td_compact(None) is None
    d = RP._td_compact({"scenario_type": "REVERSAL", "ltf": {"status": "PENDING"}, "conflicts": [{"severity": "warn"}, {"severity": "info"}]})
    assert d == {"type": "REVERSAL", "ltf": "PENDING", "m5": None, "conflicts_warn": 1, "error": None}, d
    print("ok replay ltf no-future cut")


main()
