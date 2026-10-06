#!/usr/bin/env python3
"""Strong Candle (OUR_IMPLEMENTATION): детекція, поля trace, маніпуляція, Fibonacci, без lookahead."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import o2live_synth as S  # noqa: E402
from office2 import strongcandle as SC  # noqa: E402


def bars():
    rng = np.random.default_rng(1)
    c = list(100 + np.cumsum(rng.normal(0, 0.05, 120)))
    c += [c[-1] + 2.5]                                   # імпульс вгору
    c += [c[-1] + 0.02, c[-1] + 0.03]
    b = S._bars_from_closes(c)
    b["v"] = np.full(len(c), 100.0)
    b["tbv"] = np.full(len(c), 50.0)
    b["v"][120] = 400.0
    b["tbv"][120] = 300.0                               # дельта в бік свічки
    return b


def test_detect_and_fields():
    b = bars()
    k = len(b["c"]) - 1
    d = SC.detect(b, k)
    assert d and d[0]["direction"] == "LONG" and d[0]["i"] == 120 and d[0]["vol_rel"] > 2 and d[0]["manipulation"] is False
    assert d[0]["provenance"] == "OUR_IMPLEMENTATION" and d[0]["version"] == SC.VERSION and d[0]["body_atr"] > 1
    b2 = {kk: v.copy() for kk, v in b.items()}
    b2["tbv"][120] = 50.0 - 40.0                         # дельта проти кольору → маніпуляція
    assert SC.detect(b2, k)[0]["manipulation"] is True


def test_fib_and_no_lookahead():
    b = bars()
    k = len(b["c"]) - 1
    sc = SC.detect(b, k)[0]
    fb = SC.fib(sc)
    span = sc["high"] - sc["low"]
    assert abs(fb["ote"][1] - (sc["high"] - span * 0.618)) < 1e-9 and fb["ote"][0] < fb["ote"][1] and fb["extensions"][0]["price"] > sc["high"]
    assert not SC.detect(b, 119)                         # до імпульсу його не видно
    r = SC.for_thesis(b, k, "LONG", float(b["t"][115]), [fb["ote"][0], fb["ote"][1]])
    assert r["zone_overlaps_ote"] is True
    assert SC.for_thesis(b, k, "SHORT", 0.0, [1, 2]) == {}


def main():
    for f in (test_detect_and_fields, test_fib_and_no_lookahead):
        f()
        print("ok", f.__name__)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
