"""B&R · TEST: детектор (пробій закриттям → ретест → відбій), скасування, відсутність look-ahead, симуляція."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br import detect as D
from office_br import sim as S


def _series(closes, spread=0.3):
    t = [900 * i for i in range(len(closes))]
    o = [closes[0]] + closes[:-1]
    h = [max(a, b) + spread for a, b in zip(o, closes)]
    l = [min(a, b) - spread for a, b in zip(o, closes)]
    return t, o, h, l, list(closes)


def _long_case():
    # плато ~100 з піком 103 (свінг), далі дрейф, пробій закриттям 104, відкат до 103 (ретест), відбій вгору
    base = [100 + 0.2 * ((i * 7) % 5) for i in range(40)]
    peak = [101, 102, 103.0, 102, 101.5, 101, 100.8, 101]   # свінг-хай ≈ 103 (+spread)
    pre = [100.5, 100.8, 101, 101.2, 101.4]
    brk = [104.2]                                            # перше закриття вище рівня
    retest = [103.4, 103.2]                                  # повернення до зони рівня (без закриття нижче)
    bounce = [104.0, 105.0, 106.5, 108.0, 110.0, 112.0]
    return base + peak + pre + brk + retest + bounce


def test_long_breakout_retest_confirm_found():
    t, o, h, l, c = _series(_long_case())
    sigs = D.scan(t, o, h, l, c)
    assert sigs, "очікували B&R LONG"
    s = sigs[0]
    assert s["direction"] == "LONG" and s["break_i"] < s["retest_i"] <= s["confirm_i"]
    assert s["sl"] < s["retest_extreme"] < s["entry"] < s["targets"][0]["p"]


def test_close_back_below_level_cancels():
    cs = _long_case()
    i = cs.index(104.2)
    cs[i + 1] = 101.0            # закриття назад під рівнем → скасування
    t, o, h, l, c = _series(cs)
    assert not [x for x in D.scan(t, o, h, l, c) if x["direction"] == "LONG" and x["break_i"] == i]


def test_no_lookahead_signal_independent_of_future_bars():
    t, o, h, l, c = _series(_long_case())
    full = D.scan(t, o, h, l, c)
    cut = full[0]["confirm_i"] + 1
    part = D.scan(t[:cut], o[:cut], h[:cut], l[:cut], c[:cut])
    assert part and part[0]["confirm_i"] == full[0]["confirm_i"] and abs(part[0]["entry"] - full[0]["entry"]) < 1e-9 and abs(part[0]["sl"] - full[0]["sl"]) < 1e-9


def test_short_is_mirror():
    cs = [200 - x + 100 * 0 for x in _long_case()]          # дзеркало
    t, o, h, l, c = _series(cs)
    sigs = [x for x in D.scan(t, o, h, l, c) if x["direction"] == "SHORT"]
    assert sigs and sigs[0]["sl"] > sigs[0]["entry"] > sigs[0]["targets"][0]["p"]


def test_hypotheses_are_declared():
    assert set(["pivot_k", "retest_window", "retest_tol_atr", "confirm_window", "sl_buffer_atr"]) <= set(D.HYP)


def test_sim_sl_before_tp_same_bar_and_costs():
    t, o, h, l, c = _series(_long_case() + [112.0] * 5)
    s = D.scan(t, o, h, l, c)[0]
    r = S.simulate(s, t, o, h, l, c)
    assert r["status"] in ("TP1", "SL", "OPEN", "TIMEOUT") and (r["r_net"] is None or r["r_net"] > -1.5)
    # штучно: SL і TP в одному барі → SL
    n = len(c)
    o2, h2, l2, c2 = list(o), list(h), list(l), list(c)
    j = s["confirm_i"] + 1
    h2[j] = s["targets"][0]["p"] + 1
    l2[j] = s["sl"] - 1
    r2 = S.simulate(s, t, o2, h2, l2, c2)
    assert r2["status"] == "SL" and r2["r_net"] < -1.0


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
    print("OK")
