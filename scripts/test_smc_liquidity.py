#!/usr/bin/env python3
"""SMC ліквідність: пули (swing, EQH/EQL, PDH/PDL…), життєвий цикл рівня, класи проколу (FRESH_RAID, SFP, ACCEPTED_BREAKOUT, LATE_SWEEP, WICK_ONLY, PENDING), симетрія, без lookahead."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.smc import core as K  # noqa: E402
from office2.smc import fixtures as FX  # noqa: E402
from office2.smc import liquidity as LQ  # noqa: E402
from office2.smc import structure as ST  # noqa: E402

# рівень 110 (swing high на барі 1), далі різні сценарії
BASE = [(100, 105, 99, 104), (104, 110, 103, 106), (106, 108, 104, 105), (105, 107, 103, 104), (104, 106, 102, 103), (103, 105, 101, 104)]


def lvl(p=110.0):
    return {"side": "high", "p": p, "kind": "SWING_H", "i": 1, "conf": 2, "strength": 1, "tf": "m15"}


def run(extra, p=110.0):
    b = FX.bars(BASE + extra)
    a = K.atr_arr(b, 3)
    return LQ.track(b, lvl(p), a), b


def test_sfp_same_bar_close_back():
    r, _ = run([(104, 112.5, 103, 109)])                                  # прокол 2.5, закриття нижче рівня на тому ж барі
    assert r["state"] == "SWEPT" and r["sweep"]["class"] == "SFP", r


def test_fresh_raid_reclaim_in_two_bars():
    r, _ = run([(104, 111, 103, 110.6), (110.6, 112, 110, 111.5), (111.5, 111.8, 107, 108)])
    assert r["state"] == "SWEPT" and r["sweep"]["class"] == "FRESH_RAID" and r["sweep"]["closes_beyond"] == 2, r["sweep"]


def test_accepted_breakout_then_retest_then_invalidated():
    ext = [(104, 112, 103.5, 111), (111, 114, 110.8, 113), (113, 115, 112, 114), (114, 116, 113, 115)]
    r, b = run(ext)
    assert r["state"] == "ACCEPTED_BREAKOUT" and r["sweep"] is None and r["accepted"]["closes"] == 3
    r2, _ = run(ext + [(115, 115.5, 109.9, 112)])                         # повернення до рівня зверху і утримання → RETESTED
    assert r2["state"] == "RETESTED"
    r3, _ = run(ext + [(115, 115.5, 108, 108.5)])                        # закриття назад під рівнем → INVALIDATED
    assert r3["state"] == "INVALIDATED", r3["history"]
    for rr in (r, r2, r3):
        for (s0, _), (s1, _) in zip(rr["history"], rr["history"][1:]):
            assert s1 in LQ.ALLOWED[s0], rr["history"]


def test_late_sweep_after_prior_acceptance_is_not_fresh():
    # ONDO-кейс: ціна вже ≥3 рази закрилась за цінею 110, потім повернулась; новий рівень на тій самій ціні «свіпається» — це НЕ свіжий raid
    pre = [(100, 112, 99, 111), (111, 113, 110.5, 112), (112, 114, 111, 113), (113, 114, 105, 106), (106, 108, 104, 105)]
    rows = pre + [(105, 110.4, 104, 108), (108, 109.5, 106, 107), (107, 108, 105, 106), (106, 107, 104, 105), (105, 110.8, 104, 108)]
    b = FX.bars(rows)
    a = K.atr_arr(b, 3)
    lv = {"side": "high", "p": 110.4, "kind": "SWING_H", "i": 5, "conf": 6, "strength": 1, "tf": "m15"}
    r = LQ.track(b, lv, a)
    assert r["sweep"] and r["sweep"]["class"] == "LATE_SWEEP" and r["sweep"]["prior_closes_beyond"] >= 3, r["sweep"]
    assert not LQ.sweeps_of([r])                                          # у список свіжих проколів не потрапляє


def test_wick_only_noise_and_pending():
    r, _ = run([(104, 110.02, 103, 109)])                                 # перевищення 0,02 при ATR≈4 → шум
    assert r["state"] != "SWEPT" or r["sweep"]["class"] == "WICK_ONLY"
    r2, _ = run([(104, 111.5, 103, 111)])                                 # останній бар: ще нічого не відомо — PENDING, без висновків
    assert r2["state"] in ("TOUCHED", "IDENTIFIED", "APPROACHED") and r2["pending"] and r2["sweep"] is None


def test_eqh_eql_and_pools():
    b = FX.zigzag([100, 110, 102, 110.1, 101, 110.05, 103], per_leg=3)
    a = K.atr_arr(b, 5)
    hs, ls = ST.swings(b, 1)
    lv = LQ.swing_levels(b, hs, ls, a, eq_tol_atr=0.2)
    assert any(x["kind"] == "EQH" and x["side"] == "high" for x in lv)
    assert any(x["kind"] == "SWING_L" for x in lv)
    tl = LQ.trendline_levels([{"i": 3, "conf": 4, "p": 110.0}, {"i": 9, "conf": 10, "p": 108.0}], [], 20)
    assert tl and tl[0]["kind"] == "TL_H" and tl[0]["p"] < 108.0


def test_htf_levels_previous_closed_period_only():
    t0 = 1_800_000_000.0 - (1_800_000_000 % 86400)
    d1 = {"t": np.array([t0 - 86400, t0, t0 + 86400]), "o": np.ones(3), "h": np.array([120., 130., 140.]), "l": np.array([90., 95., 99.]), "c": np.ones(3)}
    b = FX.bars([(100, 101, 99, 100)] * 4, t0=t0 + 86400 + 3600)        # зараз усередині 3-ї доби; остання ЗАКРИТА доба = друга
    lv = LQ.htf_levels(b, d1, None, None)
    pdh = [x for x in lv if x["kind"] == "PDH"][0]
    assert pdh["p"] == 130.0                                              # не 140: поточна доба ще не закрита


def test_mirror_symmetry_of_classification():
    r, b = run([(104, 112.5, 103, 109)])
    bm = K.mirror(b)
    lm = {"side": "low", "p": -110.0 * -1 if False else 110.0, "kind": "SWING_L", "i": 1, "conf": 2, "strength": 1, "tf": "m15"}
    # дзеркальний рівень: swing low на −110 у дзеркальних барах = swing high 110 у реальних
    a = K.atr_arr(b, 3)
    rm = LQ.track(bm, {"side": "low", "p": -110.0, "kind": "SWING_L", "i": 1, "conf": 2, "strength": 1, "tf": "m15"}, K.atr_arr(bm, 3))
    assert rm["sweep"]["class"] == r["sweep"]["class"] == "SFP"


def test_ledger_no_lookahead():
    b = FX.bars(BASE + [(104, 112.5, 103, 109), (109, 111, 108, 110), (110, 113, 109, 112)])
    a = K.atr_arr(b, 3)
    full = LQ.track(b, lvl(), a)
    cut = {k: v[:len(BASE) + 1] for k, v in b.items()}
    part = LQ.track(cut, lvl(), K.atr_arr(cut, 3))
    assert part["sweep"] is None or part["sweep"]["j"] == full["sweep"]["j"]


def test_internal_vs_external_liquidity():
    rg = {"low": 100.0, "high": 110.0}
    assert LQ.ie_class(105.0, rg) == "INTERNAL" and LQ.ie_class(110.0, rg) == "EXTERNAL" and LQ.ie_class(112.0, rg) == "EXTERNAL" and LQ.ie_class(105.0, None) == "EXTERNAL"

def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
