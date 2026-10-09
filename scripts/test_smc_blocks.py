#!/usr/bin/env python3
"""SMC блоки: OB (схеми 19–23), Breaker/Mitigation (24–27), Rejection (28–31), Sponsored (38), StB/BtS (34–37): поглинання, режими wick/body, MT, життєвий цикл, 2 профілі MB, симетрія."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.smc import blocks as BL  # noqa: E402
from office2.smc import core as K  # noqa: E402
from office2.smc import fixtures as FX  # noqa: E402
from office2.smc import view as V  # noqa: E402

PRE = [(101, 102, 100.5, 101.2), (101.2, 102, 100.4, 100.8)] * 4


def mk(rows):
    b = FX.bars(PRE + rows)
    return b, K.atr_arr(b, 3)


def test_bull_ob_requires_engulfing_and_mt_lifecycle():
    ob = [(100, 100.5, 98, 98.5), (98.5, 104, 98.4, 103)]
    b, a = mk(ob)
    r = BL.order_blocks_bull(b, a)
    assert len(r) == 1 and r[0]["dir"] == "LONG" and r[0]["mode"] == "body" and r[0]["zone"] == [98.5, 100.0] and abs(r[0]["mt"] - 99.25) < 1e-9
    assert r[0]["state"] == "FRESH" and r[0]["wick_low"] == 98.0
    # без поглинання (закриття не вище high блоку) — не OB (схема 19: «без поглощения не ордер блок»)
    b2, a2 = mk([(100, 100.5, 98, 98.5), (98.5, 100.4, 98.4, 100.2)])
    assert not BL.order_blocks_bull(b2, a2)
    # тінь пройшла нижче MT, але ТІЛО вище → блок живий; тест лічиться
    b3, a3 = mk(ob + [(103, 103.2, 99.0, 100.1)])
    r3 = BL.order_blocks_bull(b3, a3)[0]
    assert r3["state"] == "TESTED_ONCE" and r3["tests"] == 1
    # закриття тілом нижче MT → INVALIDATED
    b4, a4 = mk(ob + [(103, 103.2, 98.8, 99.0)])
    assert BL.order_blocks_bull(b4, a4)[0]["state"] == "INVALIDATED"
    # повторний тест → RETESTED (повторні не рекомендовані)
    b5, a5 = mk(ob + [(103, 103.2, 99.5, 101), (101, 105, 100.9, 104), (104, 104.2, 99.6, 100.5)])
    assert BL.order_blocks_bull(b5, a5)[0]["state"] == "RETESTED"


def test_ob_wick_mode_for_small_body_long_wicks():
    b, a = mk([(100, 101.5, 97.5, 99.8), (99.8, 105, 99.7, 104)])
    r = BL.order_blocks_bull(b, a)[0]
    assert r["mode"] == "wick" and r["zone"] == [97.5, 101.5]


def test_bear_ob_is_exact_mirror():
    b, a = mk([(100, 100.5, 98, 98.5), (98.5, 104, 98.4, 103)])
    bear = BL.order_blocks(K.mirror(b), a)
    dem = [x for x in BL.order_blocks(b, a) if x["dir"] == "LONG"][0]
    sup = [x for x in bear if x["dir"] == "SHORT"][0]
    assert abs(sup["zone"][0] + dem["zone"][1]) < 1e-9 and abs(sup["zone"][1] + dem["zone"][0]) < 1e-9 and abs(sup["mt"] + dem["mt"]) < 1e-9


def _supply(b):
    return [{"kind": "OB", "dir": "SHORT", "i": 8, "conf": 9, "zone": [102.0, 103.0], "wick_high": 103.4, "mt": 102.5, "state": "FRESH", "times": [0, 0]}]


BRK_ROWS = [(101, 103, 100.8, 102.2), (102.2, 102.4, 99, 100), (100, 100.4, 97, 98), (98, 99, 96.5, 98.8), (98.8, 105.5, 98.6, 105)]


def test_breaker_vs_mitigation_profiles():
    b, a = mk(BRK_ROWS)
    sup = _supply(b)
    j = len(PRE) + 4
    sw = [{"dir": "LONG", "j": j - 2, "reclaim_j": j - 1, "extreme": 96.5, "level": {"p": 97.0, "kind": "SWING_L"}, "class": "FRESH_RAID"}]
    mss = [{"kind": "MSS", "dir": "LONG", "j": j, "level": 103.0}]
    bms = [{"kind": "BMS", "dir": "LONG", "j": j, "level": 103.0}]
    bb = BL.breakers_bull(b, a, sup, sw, mss)
    assert bb and bb[0]["kind"] == "BB" and bb[0]["profile"] == "BB" and bb[0]["zone"] == [102.0, 103.0]
    mb_s = BL.breakers_bull(b, a, sup, [], mss)
    assert mb_s and mb_s[0]["kind"] == "MB" and mb_s[0]["profile"] == "MB_SCHEME"        # схеми 25–27: MSS є, максимум/мінімум не оновлено
    mb_t = BL.breakers_bull(b, a, sup, [], bms)
    assert mb_t and mb_t[0]["profile"] == "MB_TEXT"                                      # текст: BMS без MSS
    assert not BL.breakers_bull(b, a, sup, sw, [])                                       # зняття ліквідності без MSS — ще не breaker
    # BB і MB ніколи не зливаються
    assert {x["profile"] for x in bb + mb_s + mb_t} == {"BB", "MB_SCHEME", "MB_TEXT"}


def test_rejection_block_bull_wick_on_ssl():
    b, a = mk([(101, 101.2, 99.0, 100.0), (100, 100.2, 96.0, 100.1), (100.1, 103.2, 100, 103)])
    i = len(PRE) + 1
    sw = [{"dir": "LONG", "j": i, "reclaim_j": i, "extreme": 96.0, "level": {"p": 98.5, "kind": "EQL"}, "class": "SFP"}]
    r = BL.rejection_blocks_bull(b, a, sw)
    assert r and r[0]["zone"] == [96.0, 100.0] and r[0]["state"] == "REACTED" and abs(r[0]["mt"] - 98.0) < 1e-9
    # коротка тінь — не RJB
    b2, a2 = mk([(101, 101.2, 99.0, 100.0), (100, 100.2, 99.7, 100.1)])
    assert not BL.rejection_blocks_bull(b2, a2, [{"dir": "LONG", "j": len(PRE) + 1, "reclaim_j": len(PRE) + 1, "extreme": 99.7, "level": {"p": 99.9, "kind": "EQL"}, "class": "SFP"}])


def test_sponsored_two_variants_unverified():
    b, a = mk([(100, 100.5, 98, 98.5), (98.5, 104, 98.4, 103)])
    ob = BL.order_blocks_bull(b, a)
    i = ob[0]["i"]
    for lvl, var in ((98.3, "SC_BODY_ABOVE"), (99.5, "SC_CLOSE_ABOVE")):
        sw = [{"dir": "LONG", "j": i, "reclaim_j": i + 1, "extreme": 98.0, "level": {"p": lvl, "kind": "SWING_L"}, "class": "FRESH_RAID"}]
        sc = BL.sponsored_bull(b, a, ob, sw)
        assert sc and sc[0]["variant"] == var and sc[0]["verified"] is False


def test_stb_zone_between_sweep_extreme_and_mss_level():
    b, a = mk(BRK_ROWS)
    j = len(PRE) + 4
    sw = [{"dir": "LONG", "j": j - 2, "reclaim_j": j - 1, "extreme": 96.5, "level": {"p": 97.0, "kind": "SWING_L"}, "class": "FRESH_RAID"}]
    mss = [{"kind": "MSS", "dir": "LONG", "j": j, "level": 103.0}]
    r = BL.stb_bull(b, a, sw, mss, [])
    assert r and r[0]["zone"] == [96.5, 103.0] and r[0]["kind"] == "STB"


def test_view_pipeline_mirror_symmetry_on_random_walk():
    rs = np.random.RandomState(11)
    for _ in range(8):
        n = 260
        c = 100 + np.cumsum(rs.randn(n) * 0.8)
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) + np.abs(rs.randn(n)) * 0.3
        l = np.minimum(o, c) - np.abs(rs.randn(n)) * 0.3
        b = FX.bars(list(zip(o, h, l, c)))
        v, vm = V.analyze_view(b), V.analyze_view(K.mirror(b))
        assert [(e["kind"], e["j"]) for e in v["structure"]["events"]] == [(e["kind"], e["j"]) for e in vm["structure"]["events"]]
        dem = [(x["i"], x["conf"], tuple(x["zone"])) for x in v["ob_demand"]]
        sup_m = [(x["i"], x["conf"], tuple(BL.mirror_zone(x["zone"]))) for x in vm["ob_supply"]]
        assert dem == sup_m
        assert len(v["sweeps"]) == len(vm["sweeps"])


def test_ob_fractality_htf_candle_is_series_on_m15():
    b = FX.bars([(100, 101, 99, 100)] * 16, t0=1_800_000_000.0)
    h4_open = float(b["t"][4])                        # одна H4-свічка = 16 свічок M15, у даних їх 12 після відкриття
    idx = BL.ob_fractal(b, h4_open, 14400)
    assert idx == list(range(4, 16))
    assert BL.ob_fractal(b, h4_open, 3600) == [4, 5, 6, 7]       # H1-свічка = 4 свічки M15

def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
