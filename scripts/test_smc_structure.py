#!/usr/bin/env python3
"""SMC: swing (схема 04), висхідна/низхідна структура (05, 06), BMS (08), MSS + Confirm (09), не-MSS (10, 11), range/девіація (07), синхронізація ТФ, дзеркальна симетрія, відсутність lookahead."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.smc import core as K  # noqa: E402
from office2.smc import fixtures as FX  # noqa: E402
from office2.smc import structure as ST  # noqa: E402


def kinds(res, *ks):
    return [e for e in res["events"] if e["kind"] in ks]


def test_swing_three_candles_and_negative():
    for name, b, expect in FX.swing_high_cases():
        hs, _ = ST.swings(b, 1)
        assert bool(hs) == expect, name
        if expect:
            assert hs[0]["i"] == 1 and hs[0]["conf"] == 2                      # підтверджено закриттям правої свічки, не раніше
    # дзеркало: swing low
    b = FX.bars([(11, 11.5, 10.0, 10.2), (10.2, 10.4, 9.0, 10.1), (10.1, 11.0, 9.9, 10.9)])
    _, ls = ST.swings(b, 1)
    assert len(ls) == 1 and ls[0]["i"] == 1
    # рівні highs: strict не дає swing, 'first' дає перший із рівних
    eq = FX.bars([(10, 11, 9.5, 10.5), (10.5, 12, 10.2, 10.6), (10.6, 12, 10.0, 10.1), (10.1, 11, 9.8, 9.9)])
    assert not ST.swings(eq, 1, "strict")[0]
    assert [s["i"] for s in ST.swings(eq, 1, "first")[0]] == [1]


def test_uptrend_bms_chain_and_labels():
    b = FX.uptrend()
    r = ST.analyze(b)
    assert r["trend"] == "UP"
    bms = kinds(r, "BMS")
    assert len(bms) >= 3 and all(e["dir"] == "LONG" for e in bms)
    labs = [x["label"] for x in r["labels"] if x["type"] == "high"]
    assert labs[:3] == ["H0", "HH", "HH"], labs
    lows = [x["label"] for x in r["labels"] if x["type"] == "low"]
    assert "HL" in lows and "LL" not in lows
    assert r["protected_low"] is not None and r["structural_high"] is not None
    # BMS лише за закриттям: жодна подія не позначена на барі, де закриття не за рівнем
    for e in bms:
        assert b["c"][e["j"]] > e["level"]


def test_downtrend_bms_chain():
    r = ST.analyze(FX.downtrend())
    assert r["trend"] == "DOWN"
    bms = kinds(r, "BMS")
    assert len(bms) >= 3 and all(e["dir"] == "SHORT" for e in bms)
    assert r["protected_high"] is not None


def test_mss_then_confirm():
    b = FX.mss_confirm()
    r = ST.analyze(b)
    mss = kinds(r, "MSS")
    assert len(mss) == 1 and mss[0]["dir"] == "SHORT"
    assert b["c"][mss[0]["j"]] < mss[0]["level"]
    cf = kinds(r, "CONFIRM")
    assert len(cf) == 1 and cf[0]["dir"] == "SHORT" and cf[0]["j"] > mss[0]["j"]
    assert r["trend"] == "DOWN"
    # MSS іде ПІСЛЯ останнього BMS і ламає захищений мінімум (початок останньої ноги), а не довільний
    last_bms = kinds(r, "BMS")[-1]
    assert mss[0]["level"] == last_bms["protected"] or abs(mss[0]["level"] - last_bms["protected"]) < 1e-9


def test_correction_break_is_not_mss():
    b = FX.not_mss()
    r = ST.analyze(b)
    assert not kinds(r, "MSS"), kinds(r, "MSS")
    assert kinds(r, "CORRECTION_BREAK"), "злам внутрішнього мінімуму має бути зафіксований як корекція"
    assert r["trend"] == "UP"


def test_transition_before_confirm_and_failed_mss():
    # MSS без Confirm: стан TRANSITION
    b = FX.zigzag([100, 110, 104, 118, 111, 126, 108], per_leg=4)
    r = ST.analyze(b)
    assert kinds(r, "MSS") and not kinds(r, "CONFIRM") and r["trend"] == "TRANSITION"
    assert r["transition"]["to"] == "DOWN"
    # MSS_FAILED: після MSS закриття над вершиною → тренд відновлюється з BMS
    b2 = FX.zigzag([100, 110, 104, 118, 111, 126, 108, 130], per_leg=4)
    r2 = ST.analyze(b2)
    assert kinds(r2, "MSS_FAILED") and r2["trend"] == "UP"


def test_range_and_deviation():
    b = FX.range_with_deviation()
    a = K.atr_arr(b, 5)
    hs, ls = ST.swings(b, 1)
    rg = ST.detect_range(b, hs, ls, a, upto=24)                      # коридор до девіації
    assert rg and rg["low"] < rg["eq"] < rg["high"] and abs(rg["eq"] - (rg["high"] + rg["low"]) / 2) < 1e-9 and set(rg["levels"]) == {"0", "0.5", "1"}
    dev = ST.deviation_events(b, rg, a)
    assert any(e["kind"] == "DEVIATION" and e["side"] == "high" and e["dir"] == "SHORT" for e in dev), dev


def test_accepted_breakout_is_expansion_not_deviation():
    base = FX.zigzag([100, 110, 102, 109, 101, 110, 103], per_leg=3)
    up = FX.bars([(103, 112, 103, 111.5), (111.5, 114, 111, 113.5), (113.5, 116, 113, 115.5), (115.5, 118, 115, 117)], t0=float(base["t"][-1]) + 900)
    b = FX.concat(base, up)
    a = K.atr_arr(b, 5)
    hs, ls = ST.swings(base, 1)
    rg = ST.detect_range(base, hs, ls, K.atr_arr(base, 5))
    assert rg
    dev = ST.deviation_events(b, rg, a)
    assert any(e["kind"] == "EXPANSION" and e["dir"] == "LONG" for e in dev) and not any(e["kind"] == "DEVIATION" and e["side"] == "high" for e in dev), dev


def test_mirror_symmetry():
    for fx in (FX.uptrend(), FX.mss_confirm(), FX.not_mss()):
        r = ST.analyze(fx)
        m = ST.analyze(K.mirror(fx))
        assert [(e["kind"], e["j"]) for e in r["events"]] == [(e["kind"], e["j"]) for e in m["events"]]
        assert [e["dir"] for e in r["events"]] == ["SHORT" if e["dir"] == "LONG" else "LONG" for e in m["events"]]


def test_no_lookahead():
    rs = np.random.RandomState(7)
    steps = rs.randn(300) * 1.2
    c = 100 + np.cumsum(steps)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + np.abs(rs.randn(300)) * 0.5
    l = np.minimum(o, c) - np.abs(rs.randn(300)) * 0.5
    full = FX.bars(list(zip(o, h, l, c)))
    for cut in (80, 150, 220):
        part = {k: v[:cut] for k, v in full.items()}
        rp = ST.analyze(part)
        rf = ST.analyze(full)
        ev_full = [(e["kind"], e["j"], round(e["level"], 9)) for e in rf["events"] if e["j"] < cut]
        ev_part = [(e["kind"], e["j"], round(e["level"], 9)) for e in rp["events"]]
        assert ev_full == ev_part, (cut, ev_full[-3:], ev_part[-3:])


def test_random_walk_invariants():
    rs = np.random.RandomState(3)
    for _ in range(25):
        n = 200
        c = 50 + np.cumsum(rs.randn(n))
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) + np.abs(rs.randn(n)) * 0.4
        l = np.minimum(o, c) - np.abs(rs.randn(n)) * 0.4
        b = FX.bars(list(zip(o, h, l, c)))
        r = ST.analyze(b)
        js = [e["j"] for e in r["events"]]
        assert js == sorted(js) and all(0 <= j < n for j in js)
        assert r["trend"] in ("UP", "DOWN", "TRANSITION", "RANGE", "UNKNOWN")
        for e in r["events"]:
            if e["kind"] == "MSS":
                assert (e["dir"] == "SHORT" and b["c"][e["j"]] < e["level"]) or (e["dir"] == "LONG" and b["c"][e["j"]] > e["level"])


def test_tf_sync_local_correction_vs_htf_change():
    h4 = {"trend": "UP"}
    m15 = {"trend": "TRANSITION", "transition": {"to": "DOWN"}}
    s = ST.tf_sync({"h4": h4, "m15": m15})
    assert s["htf_bias"] == "UP" and not s["aligned"] and "корекція" in s["notes"][0]
    s2 = ST.tf_sync({"h4": h4, "m15": {"trend": "UP"}})
    assert s2["aligned"]


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
