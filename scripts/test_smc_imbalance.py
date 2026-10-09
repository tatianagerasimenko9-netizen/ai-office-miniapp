#!/usr/bin/env python3
"""SMC неефективність: FVG (схеми 13, 14), рівні 0,25/0,5/0,75/FF, тіла vs тіні, VI, Void, Gap, BPR, симетрія, без lookahead."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.smc import core as K  # noqa: E402
from office2.smc import fixtures as FX  # noqa: E402
from office2.smc import imbalance as IM  # noqa: E402

PRE = [(100, 101, 99, 100.5)] * 3 + [(100.5, 101.5, 99.5, 100.2)] * 2
# бичачий FVG: свічка A high=101, B імпульс, C low=104 → зона [101,104]
FV = [(100, 101, 99.5, 100.8), (100.8, 106, 100.7, 105.5), (105.5, 107, 104, 106.5)]


def mk(extra):
    b = FX.bars(PRE + FV + extra)
    return b, K.atr_arr(b, 3)


def test_fvg_geometry_and_efficient_negative():
    b, a = mk([])
    f = IM.fvgs(b, a)
    assert len(f) == 1 and f[0]["dir"] == "LONG" and f[0]["zone"] == [101.0, 104.0] and f[0]["state"] == "ACTIVE"
    # ефективне ціноутворення (схема 14 ліворуч): тіні сусідніх свічок перекриваються → FVG немає
    eff = FX.bars([(100, 102, 99, 101.5), (101.5, 103.5, 101, 103), (103, 105, 101.8, 104.5)])
    assert not IM.fvgs(eff, K.atr_arr(eff, 2))


def test_fill_levels_and_respect_wick_vs_body():
    b, a = mk([(106.5, 107, 103.0, 105.0)])                               # тінь у зону до 103 (глибина 1/3) — «повага»
    f = IM.fvgs(b, a)[0]
    assert f["state"] == "RESPECTED" and f["levels"]["0.25"] and not f["levels"]["0.5"] and IM.respected(f)
    b2, a2 = mk([(106.5, 107, 102.0, 105.0)])                              # тінь до 102 (2/3 зони)
    f2 = IM.fvgs(b2, a2)[0]
    assert f2["levels"]["0.5"] and not f2["levels"]["FF"] and f2["state"] == "RESPECTED"
    b3, a3 = mk([(106.5, 107, 100.5, 105.0)])                              # тінь наскрізь (FF), тіло лишилось вище — зона ще працює
    f3 = IM.fvgs(b3, a3)[0]
    assert f3["levels"]["FF"] and f3["state"] == "FILLED_RESPECTED" and f3["body_frac"] < 0.5
    b4, a4 = mk([(106.5, 106.8, 101.9, 102.0)])                            # тіло закрилось за серединою (102.5), не наскрізь
    assert IM.fvgs(b4, a4)[0]["state"] == "PARTIAL"
    b5, a5 = mk([(106.5, 106.8, 100.2, 100.4)])                            # тіло закрилось нижче зони → BROKEN
    assert IM.fvgs(b5, a5)[0]["state"] == "BROKEN"


def test_mirror_bearish_fvg():
    b, a = mk([(106.5, 107, 102.0, 105.0)])
    m = K.mirror(b)
    fm = IM.fvgs(m, K.atr_arr(m, 3))[0]
    f = IM.fvgs(b, a)[0]
    assert fm["dir"] == "SHORT" and f["state"] == fm["state"] and abs(fm["zone"][0] + f["zone"][1]) < 1e-9


def test_vi_void_gap_bpr():
    rows = [(100, 101, 99, 100.5)] * 3 + [(100, 104, 99.8, 103.8), (104.6, 108, 104.0, 107.8)]
    b = FX.bars(rows)
    a = K.atr_arr(b, 3)
    vi = IM.volume_imbalances(b, a)
    assert vi and vi[0]["dir"] == "LONG" and "проксі" in vi[0]["note"]
    void = FX.bars([(100, 101, 99, 100.5)] * 3 + [(100.5, 104, 100.4, 103.8), (103.8, 107.5, 103.7, 107.2), (107.2, 111, 107, 110.8), (110.8, 114.3, 110.6, 114)])
    v = IM.liquidity_voids(void, K.atr_arr(void, 3))
    assert v and v[0]["bars"] >= 3 and v[0]["dir"] == "LONG"
    g = FX.bars([(100, 101, 99, 100.5), (103, 104, 102.5, 103.5)])
    assert IM.opening_gaps(g, K.atr_arr(g, 1))
    # BPR: бичачий FVG, потім ведмежий, що перекриває його діапазон
    rows = [(100, 101, 99, 100.5)] * 3 + [(100.5, 101, 100, 100.8), (100.8, 106, 100.7, 105.5), (105.5, 107, 104, 106.5), (106.5, 106.8, 102, 102.5), (102.5, 102.9, 99, 100)]
    bb = FX.bars(rows)
    fv = IM.fvgs(bb, K.atr_arr(bb, 3))
    assert {f["dir"] for f in fv} == {"LONG", "SHORT"}
    bp = IM.bprs(fv)
    assert bp and bp[0]["zone"][1] > bp[0]["zone"][0]


def test_no_lookahead_fill():
    b, a = mk([(106.5, 107, 102.0, 105.0), (105, 106, 104.5, 105.5)])
    part = {k: v[:len(PRE) + 3] for k, v in b.items()}
    fp = IM.fvgs(part, K.atr_arr(part, 3))[0]
    assert fp["state"] == "ACTIVE"                                          # на момент формування відпрацювання ще невідоме


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
