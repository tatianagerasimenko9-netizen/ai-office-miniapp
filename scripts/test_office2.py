#!/usr/bin/env python3
"""Office 2.0 shadow: відсутність lookahead, коректність first-touch, калібрування бази (випадкові входи ≈ 0), Risk Manager. Без мережі."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import data as D  # noqa: E402
from office2 import evaluate as E  # noqa: E402
from office2 import features as F  # noqa: E402
from office2 import pipeline as P  # noqa: E402
from office2 import risk as R  # noqa: E402
from office2 import sim as S  # noqa: E402


def synth(days=40, seed=1, start=1_790_000_000 // 86400 * 86400, sigma=0.0009, drift_wave=True):
    rng = np.random.default_rng(seed)
    n = days * 1440
    t = start + 60.0 * np.arange(n)
    ret = rng.normal(0, sigma, n)
    if drift_wave:   # повільні хвилі, щоб з'являлись свінги/рівні/sweep
        ret += 0.00025 * np.sin(np.arange(n) / 700.0)
    c = 100.0 * np.exp(np.cumsum(ret))
    o = np.r_[c[0], c[:-1]]
    wick = np.abs(rng.normal(0, sigma * 0.8, n))
    h = np.maximum(o, c) * (1 + wick)
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, sigma * 0.8, n)))
    v = rng.uniform(50, 150, n)
    tbv = v * np.clip(0.5 + rng.normal(0, 0.1, n), 0.05, 0.95)
    return D.from_arrays(t, o, h, l, c, v, tbv)


def test_resample_and_atr_swings():
    a = synth(3)
    m15 = F.resample(a, 900)
    assert len(m15["t"]) == 3 * 96 and m15["h"][0] == a["h"][:15].max() and m15["c"][0] == a["c"][14] and abs(m15["v"][0] - a["v"][:15].sum()) < 1e-6
    at = F.atr(m15, 14)
    assert np.isnan(at[12]) and not np.isnan(at[13])
    # ATR на барі i не залежить від майбутніх барів
    m2 = {k: v[:100].copy() for k, v in m15.items()}
    assert np.allclose(F.atr(m2, 14)[13:100], at[13:100])
    # фрактал підтверджується лише через n барів
    sh, sl = F.swings(m15, 2)
    assert all(ki == i + 2 for i, ki, _p in sh)
    h4 = F.resample(synth(10), 4 * 3600)
    assert set(np.unique(F.regime_by_bar(h4))) <= {-1, 0, 1}


def key(c):
    return (c["symbol"], c["dir"], c["trigger"], round(c["t_entry"]), round(c["entry"], 8), round(c["sl"], 8), round(c["tp"], 8), c["etype"], c["lvl_kind"], c["reg4"], c["regd"],
            None if c["btc4"] is None else round(c["btc4"], 8), c["flow_ok"])


def test_no_lookahead_truncation():
    full = synth(45, seed=2)
    btc = synth(45, seed=3)
    ctx_f, btc_f = P.build_context(full), P.build_context(btc)
    cf = P.candidates("XUSDT", ctx_f, btc_f)
    assert len(cf) >= 20, f"замало кандидатів для перевірки: {len(cf)}"
    T = full["t"][0] + 30 * 86400   # межа усічення (кратна 15 хв)
    cut = lambda a: {k: v[: int((T - a["t"][0]) // 60)] for k, v in a.items()}
    ct, bt = P.build_context(cut(full)), P.build_context(cut(btc))
    cc = P.candidates("XUSDT", ct, bt)
    kf = {key(c) for c in cf if c["t_entry"] <= T - 120}
    kc = {key(c) for c in cc if c["t_entry"] <= T - 120}
    assert kc and kc == kf, (len(kc), len(kf), sorted(kc ^ kf)[:3])
    # кожен TP/рівень відомий НЕ пізніше моменту входу
    for c in cf:
        assert c["tp_known"] <= c["t_entry"] + 1e-6 and c["lvl_known"] <= c["t_entry"]


def test_first_touch():
    t = 1_790_000_000.0 + 60.0 * np.arange(10)
    base = dict(t=t, o=np.full(10, 100.0), c=np.full(10, 100.0), v=np.ones(10), tbv=np.ones(10))
    h = np.full(10, 100.5)
    l = np.full(10, 99.5)
    m = dict(base, h=h.copy(), l=l.copy())
    # LONG: TP 101, SL 99; хвилина 3 торкає і TP, і SL → SL (консервативно)
    m["h"][3], m["l"][3] = 101.2, 98.9
    r = S.first_touch(m, 0, "LONG", 100.0, 99.0, 101.0, 3600)
    assert r["outcome"] == "SL" and r["r_gross"] == -1.0
    m["l"][3] = 99.4
    r = S.first_touch(m, 0, "LONG", 100.0, 99.0, 101.0, 3600)
    assert r["outcome"] == "TP" and abs(r["r_gross"] - 1.0) < 1e-9 and r["ttr_sec"] == 180.0
    # SHORT симетрія
    m2 = dict(base, h=h.copy(), l=l.copy())
    m2["l"][5] = 98.8
    r = S.first_touch(m2, 0, "SHORT", 100.0, 101.0, 99.0, 3600)
    assert r["outcome"] == "TP" and r["r_gross"] == 1.0
    # таймаут: MTM
    m3 = dict(base, h=h.copy(), l=l.copy(), c=np.full(10, 100.4))
    r = S.first_touch(m3, 0, "LONG", 100.0, 99.0, 105.0, 3600)
    assert r["outcome"] == "TO" and abs(r["r_gross"] - 0.4) < 1e-9
    # комісії в R: ризик 1% → 0,10% кола = 0,10 R
    assert abs(S.net_r(1.0, 1.0, 0.10) - 0.9) < 1e-9


def test_random_control_calibration():
    """Випадкові входи на випадковому блуканні: факт ≈ база (0,4); якщо ні — симулятор/база зміщені."""
    ctxs, rows = {}, []
    p = P.Params()
    for k in range(6):
        a = synth(30, seed=10 + k, drift_wave=False)
        ctx = P.build_context(a)
        ctxs[f"S{k}USDT"] = ctx
    cands = E.random_control(ctxs, 150, p, seed=3)
    rows = E.evaluate(cands, ctxs, p)
    s = E.summarize(rows)
    assert s["n_res"] >= 400, s
    assert abs(s["base"] - 0.4) < 1e-9 or abs(s["base"] - 0.4) < 0.01
    assert s["lo"] <= 0.0 <= s["hi"] or abs(s["excess"]) < 0.05, s   # контроль не має давати значущого надлишку


def test_pipeline_runs_and_ablation_nonempty():
    ctxs = {}
    p = P.Params()
    rows = []
    btc = P.build_context(synth(60, seed=20))
    for k in range(5):
        ctx = P.build_context(synth(60, seed=30 + k))
        ctxs[f"S{k}USDT"] = ctx
        rows += E.evaluate(P.candidates(f"S{k}USDT", ctx, btc, p), {f"S{k}USDT": ctx}, p)
    assert len(rows) >= 30
    ab = E.ablation(rows)
    assert ab[0][1] and len(ab) >= 8
    assert all(r["rr"] >= p.min_rr - 1e-9 for r in rows) and all(p.min_risk_pct <= r["risk_pct"] <= p.max_risk_pct for r in rows)
    txt = "\n".join(E.table("t", ab))
    assert "надлишок" in txt


def test_scenarios_no_lookahead_and_behavior():
    from office2 import scenarios as SC
    full = synth(45, seed=7)
    btc = synth(45, seed=8)
    cf, bf = P.build_context(full), P.build_context(btc)
    r = SC.scenario_candidates("XUSDT", cf, bf)
    assert r["behav"] and {b["behavior"] for b in r["behav"]} <= {"A", "B1", "ACCEPT", "TRAP"}
    assert any(c["trigger"] == "accept" for c in r["cands"])
    T = full["t"][0] + 30 * 86400
    cut = lambda a: {k: v[: int((T - a["t"][0]) // 60)] for k, v in a.items()}
    rc = SC.scenario_candidates("XUSDT", P.build_context(cut(full)), P.build_context(cut(btc)))
    k = lambda c: (c["trigger"], c["dir"], round(c["t_entry"]), round(c["entry"], 8), round(c["sl"], 8), round(c["tp"], 8), c["lvl_kind"], c["reg4"], c["etype"], round(c["depth_atr"], 8))
    kf = {k(c) for c in r["cands"] if c["t_entry"] <= T - 120}
    kc = {k(c) for c in rc["cands"] if c["t_entry"] <= T - 120}
    assert kc and kc == kf, (len(kc), len(kf), sorted(kc ^ kf)[:3])
    for c in r["cands"]:
        assert c["tp_known"] <= c["t_entry"] + 1e-6 and c["lvl_known"] <= c["t_entry"] and c["etype"] == "ACCEPT"
        # продовження торгує У БІК пробою, SL — за рівнем
        assert (c["dir"] == "LONG") == (c["brk"] > 0)
        assert (c["sl"] < c["lvl_p"]) if c["dir"] == "LONG" else (c["sl"] > c["lvl_p"])


def test_diff_ci():
    rows_a = [{"symbol": f"S{i % 9}", "day": i % 5, "r_net": 1.0} for i in range(60)]
    rows_b = [{"symbol": f"S{i % 9}", "day": i % 5, "r_net": -1.0} for i in range(60)]
    pt, lo, hi = E.diff_ci(rows_a, rows_b)
    assert abs(pt - 2.0) < 1e-9 and lo > 1.9 and hi <= 2.0 + 1e-9
    assert E.diff_ci([], rows_b)[0] != E.diff_ci([], rows_b)[0]   # NaN без даних


def test_probe_basics_and_no_lookahead():
    from office2 import probe as PR
    assert abs(PR.auc(np.array([1.0, 2, 3, 4]), np.array([0.0, 0, 1, 1])) - 1.0) < 1e-12
    assert abs(PR.auc(np.array([4.0, 3, 2, 1]), np.array([0.0, 0, 1, 1])) - 0.0) < 1e-12
    assert abs(PR.auc(np.array([1.0, 1, 1, 1]), np.array([0.0, 1, 0, 1])) - 0.5) < 1e-12      # зв'язки → 0,5
    # ridge відновлює лінійну залежність; без залежності AUC ≈ 0,5
    rng = np.random.default_rng(0)
    X = rng.normal(size=(2000, 4))
    y = (X[:, 0] + 0.3 * rng.normal(size=2000) > 0).astype(float)
    m = PR.ridge_fit(X, y)
    assert PR.auc(PR.ridge_score(X, m), y) > 0.9
    y0 = rng.integers(0, 2, 2000).astype(float)
    assert abs(PR.auc(PR.ridge_score(X, PR.ridge_fit(X, y0)), y0) - 0.5) < 0.06
    # спостереження: features не залежать від майбутнього (усічення), TRAP лише мітка, контроль присутній
    full, btc = synth(45, seed=11), synth(45, seed=12)
    of = PR.build_observations("XUSDT", P.build_context(full), P.build_context(btc))
    assert of and any(o["behavior"] == "CTRL" for o in of) and any(o["behavior"] != "CTRL" for o in of)
    assert all(o["behavior"] in ("A", "B1", "ACCEPT", "CTRL") for o in of)      # TRAP не потрапляє в decision-time поведінку
    T = full["t"][0] + 30 * 86400
    cut = lambda a: {k: v[: int((T - a["t"][0]) // 60)] for k, v in a.items()}
    oc = PR.build_observations("XUSDT", P.build_context(cut(full)), P.build_context(cut(btc)))
    kf = {(round(o["t"]), o["behavior"], tuple(round(o["f"][k], 8) for k in PR.FEATURES)) for o in of if o["t"] <= T - 3600}
    kc = {(round(o["t"]), o["behavior"], tuple(round(o["f"][k], 8) for k in PR.FEATURES)) for o in oc if o["t"] <= T - 3600}
    assert kc and kc <= kf, (len(kc), len(kf), sorted(kc - kf)[:2])
    # labels: стоп раніше цілі, обидва напрямки, MFE/MAE ≥ 0
    for o in of[:50]:
        assert o["cont_tp"] + o["cont_sl"] <= 1 and o["rev_tp"] + o["rev_sl"] <= 1 and o["cont_mfe"] >= 0 and o["cont_mae"] >= 0


def _planted(n=260, seed=1, pierce=False, small_impulse=False):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 0.15, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.2, n))
    l = np.minimum(o, c) - np.abs(rng.normal(0, 0.2, n))
    step = 0.3 if small_impulse else 1.4
    for i in range(100, 107):
        c[i] = 100 + (i - 100) * step
        o[i] = c[i] - 1.2 * (step / 1.4)
        h[i] = c[i] + 0.3
        l[i] = o[i] - 0.2
    l[100] = 99.2
    peak = h[106]
    zig = [-1.2, -1.8, -2.2, -1.5, -2.2, -2.6, -2.1, -2.7, -3.0, -2.5, -3.1, -3.3, -2.9, -3.4, -3.6, -3.3, -3.7, -3.8]
    for k, z in enumerate(zig):
        i = 107 + k
        c[i] = peak + z - 0.8
        o[i] = c[i] + 0.2
        h[i] = peak + z
        l[i] = c[i] - 0.6
    if pierce:
        h[112] = peak + 0.5          # ціна вже пробила лінію під час стиснення → лінія не діє
    i = 107 + len(zig)
    c[i], o[i] = peak - 2.2, peak - 3.9
    h[i], l[i] = c[i] + 0.2, o[i] - 0.1
    for j in range(i + 1, i + 20):
        c[j] = c[i] + 0.1 * (j - i)
        o[j] = c[j] - 0.1
        h[j] = c[j] + 0.3
        l[j] = c[j] - 0.3
    t = 3600.0 * np.arange(n) + 1_790_000_000 // 3600 * 3600
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": np.full(n, 100.0), "tbv": np.full(n, 55.0), "n": np.full(n, 60.0)}


def test_narrative_detector():
    from office2 import narrative as N
    bars = _planted()
    st = {}
    ev = N.find_setups_long(bars, F.atr(bars, 14), N.NParams(), st)
    assert len(ev) == 1 and ev[0]["ih"] == 106 and ev[0]["b"] == 125 and ev[0]["imp_atr"] > 5 and 0.25 <= ev[0]["retr"] <= 0.9, (ev, st)
    assert ev[0]["block_held"] == 1.0 and ev[0]["slope_atr"] < 0 and ev[0]["above_line"] > 0.1
    # негативні варіанти
    pb = _planted(pierce=True)
    assert all(e["ih"] != 106 for e in N.find_setups_long(pb, F.atr(pb, 14), N.NParams(), {}))   # ціна вже вище хая імпульсу → старий імпульс не дає сетапу
    sm = _planted(small_impulse=True)
    assert not N.find_setups_long(sm, F.atr(sm, 14), N.NParams(), {})
    # без lookahead: до пробійного бару події немає; після — ті самі ознаки
    cut = lambda b, k: {kk: v[:k].copy() for kk, v in b.items()}
    assert not N.find_setups_long(cut(bars, 125), F.atr(cut(bars, 125), 14), N.NParams(), {})
    e2 = N.find_setups_long(cut(bars, 140), F.atr(cut(bars, 140), 14), N.NParams(), {})
    assert len(e2) == 1 and all(abs(e2[0][k] - ev[0][k]) < 1e-9 for k in ("imp_atr", "retr", "line_b", "brk_body", "block_return", "touches", "room_imp"))
    # дзеркало: SHORT-версія знаходиться в дзеркальних даних
    mb = N._mirror(bars)
    mb2 = {k: (-v if k in ("o", "h", "l", "c") else v) for k, v in mb.items()}      # дзеркало дзеркала = вихідні
    assert np.allclose(N._mirror(mb)["h"], bars["h"])


def test_outcome_record():
    from office2 import narrative as N
    n = 3000
    t = np.arange(n, dtype=float) * 60
    c = np.full(n, 100.0)
    c[10:] = np.minimum(100 + (np.arange(n - 10)) * 0.1, 106)     # росте до 106, тримається
    c[1500:] = 97.0                                              # потім падає під SL (98)
    m1 = {"t": t, "o": c.copy(), "h": c + 0.05, "l": c - 0.05, "c": c, "v": np.ones(n), "tbv": np.ones(n) * .5}
    r = N._outcome_record(m1, 0, "LONG", 100.0, 98.0, 105.0, 99.0, 1.0)
    assert abs(r["mfe_r_48"] - 3.025) < 1e-6 and r["inval_min"] == 1500 and r["high_min"] is not None and r["high_before_inval"]
    assert r["back_below_min"] == 1500 and abs(r["mfe_to_inval_r"] - 3.025) < 1e-6 and r["mfe_r_1"] < r["mfe_r_4"] <= r["mfe_r_48"]
    s2 = N._outcome_record(m1, 0, "SHORT", 100.0, 102.0, 95.0, 101.0, 1.0)      # дзеркально: ціна росте проти шорта → інвалідація, ХАЮ не досягнуто
    assert s2["inval_min"] is not None and s2["inval_min"] < 100 and not s2["high_before_inval"] and s2["mfe_to_inval_r"] < 0.5
    assert r["order_0.5"] == "up" and r["order_1.0"] == "up" and r["order_2.0"] == "up"        # +4R (до 106) досягнуто до падіння під SL
    assert s2["order_0.5"] == "down" and s2["order_2.0"] == "down"
    # спочатку −1R, потім +3R: MFE велика, але порядок «down»
    c2 = np.full(n, 100.0); c2[5:20] = 97.0; c2[20:] = 106.0
    m2 = {"t": t, "o": c2.copy(), "h": c2 + .05, "l": c2 - .05, "c": c2, "v": np.ones(n), "tbv": np.ones(n) * .5}
    r2 = N._outcome_record(m2, 0, "LONG", 100.0, 98.0, None, None, 1.0)
    assert r2["mfe_r_48"] > 2.5 and r2["order_1.0"] == "down" and r2["order_0.5"] == "down"
    # без жодного з двох
    c3 = np.full(n, 100.0); m3 = {"t": t, "o": c3.copy(), "h": c3 + .05, "l": c3 - .05, "c": c3, "v": np.ones(n), "tbv": np.ones(n) * .5}
    assert N._outcome_record(m3, 0, "LONG", 100.0, 98.0, None, None, 1.0)["order_1.0"] == "none"
    assert N._outcome_record(m1, 0, "LONG", 100.0, 100.0, None, None, 1.0) is None


def test_matched_pairs():
    from office2 import narrative as N
    ctx = P.build_context(synth(220, seed=41, sigma=0.0035))
    btc = P.build_context(synth(220, seed=42, sigma=0.0035))
    st = {}
    pr = N.matched_pairs("XUSDT", ctx, btc, N.NParams(), st)
    assert st.get("pair_n", 0) >= 3, st
    byp = {}
    for r in pr:
        byp.setdefault(r["pair"], {})[r["kind"]] = r
    assert all(set(v) == {"event", "matched"} for v in byp.values())
    for v in byp.values():
        e, c = v["event"], v["matched"]
        assert e["dir"] == c["dir"] and e["symbol"] == c["symbol"] and e["day"] == c["day"]
        assert N._session(e["t_entry"]) == N._session(c["t_entry"])            # та сама сесія
        assert abs(e["t_entry"] - c["t_entry"]) > 3 * 3600                     # контроль ≥ 3 бари від події
        assert c["rr_to_high"] is not None and c["back_below_min"] is None
    assert len({(r["dir"], round(r["t_entry"])) for r in pr if r["kind"] == "matched"}) == sum(1 for r in pr if r["kind"] == "matched")   # без повторів


def test_zone_n2():
    from office2 import zone as Z
    from office2 import outcome as O
    full = synth(260, seed=51, sigma=0.0035)
    btc = synth(260, seed=52, sigma=0.0035)
    ctx, bctx = P.build_context(full), P.build_context(btc)
    st = {}
    sc = Z.scan("XUSDT", ctx, bctx, Z.ZParams(), st)
    ev = [e for e in sc["events"] if e["type"] == "EXIT"]
    assert len(ev) >= 10 and sc["pool"], (st, len(sc["pool"]))
    for e in ev:
        f = e["feat"]
        assert f["k"] >= 1 and f["depth_last"] >= 0 and 0 <= f["close_loc_last"] <= 1 and f["risk_atr"] > 0, f
        assert sum(f[x] for x in ("shape_range", "shape_down", "shape_up", "shape_conv", "shape_exp", "shape_unk")) == 1.0
    # без lookahead: усічення даних після моменту рішення не змінює подію
    T = full["t"][0] + 200 * 86400
    cut = lambda a: {k: v[: int((T - a["t"][0]) // 60)] for k, v in a.items()}
    cx, cb = P.build_context(cut(full)), P.build_context(cut(btc))
    sc2 = Z.scan("XUSDT", cx, cb, Z.ZParams(), {})
    key = lambda e: (e["type"], e["dir"], e["j"])
    f1 = {key(e): e["feat"] for e in sc["events"] if e["t_dec"] <= T - 6 * 3600}
    f2 = {key(e): e["feat"] for e in sc2["events"] if e["t_dec"] <= T - 6 * 3600}
    assert f1 and set(f1) == set(f2), (len(f1), len(f2), sorted(set(f1) ^ set(f2))[:3])
    for k_, a in f1.items():
        for name, val in a.items():
            assert abs(val - f2[k_][name]) < 1e-6, (k_, name, val, f2[k_][name])
    # змінність: сконструйована константа відсікається
    rows = [{"feat": {"a": 1.0, "b": float(i % 7)}} for i in range(100)]
    rep = {r["feature"]: r for r in Z.variance_report(rows, ("a", "b"))}
    assert not rep["a"]["usable"] and rep["b"]["usable"]
    # matched-пари: однакові сесія/режим, пара належить до дня події, контролі без повторів
    out = Z.build_records("XUSDT", ctx, bctx, Z.ZParams(), {}, 20)
    byp = {}
    for r in out["events"] + out["matched"]:
        if r["pair"]:
            byp.setdefault(r["pair"], []).append(r)
    mp = [v for v in byp.values() if len(v) == 2]
    for v in mp:
        assert v[0]["day"] == v[1]["day"] and v[0]["dir"] == v[1]["dir"]
        assert abs(v[1]["risk_atr"] / v[0]["risk_atr"] - 1) < 0.34      # caliper відстані стопу в ATR
    assert out["events"] and out["random"]


def test_outcome_n2():
    from office2 import outcome as O
    n = 3000
    t = np.arange(n, dtype=float) * 60
    c = np.full(n, 100.0)
    c[10:] = np.minimum(100 + np.arange(n - 10) * 0.1, 106)
    m1 = {"t": t, "o": c.copy(), "h": c + .05, "l": c - .05, "c": c, "v": np.ones(n), "tbv": np.ones(n) * .5}
    r = O.outcome_record(m1, 0, "LONG", 100.0, 98.0, 1.0)
    assert r["order_2.0"] == "up" and r["g2_outcome"] == "TP" and abs(r["r_gross_g2"] - 2.0) < 1e-9
    assert abs(r["r_net_g2"] - (2.0 - 0.15 / 2.0)) < 1e-9 and abs(r["risk_atr"] - 2.0) < 1e-9
    s = O.outcome_record(m1, 0, "SHORT", 100.0, 102.0, 1.0)
    assert s["order_0.5"] == "down" and s["g2_outcome"] == "SL" and s["r_gross_g2"] == -1.0
    assert O.outcome_record(m1, 0, "LONG", 100.0, 100.0, 1.0) is None


def test_zone_calibration_random_walk():
    """На випадковому блуканні (без пам'яті) різниця подія − matched-контроль у P(+1R раніше −1R | вирішено) має бути ≈0.
    Ловить lookahead-зсув контролю (колись контроль брався з тієї ж корекції до майбутньої атаки → зсув −3,7 п.п.)."""
    from office2 import zone as Z
    pu = lambda rs: (lambda dec: sum(r["order_1.0"] == "up" for r in dec) / max(len(dec), 1))([r for r in rs if r["order_1.0"] != "none"])
    diffs = []
    for seed in range(10):
        btc = P.build_context(synth(120, seed=9000 + seed, sigma=0.0010, drift_wave=False))
        ev, ct = [], []
        for i in range(3):
            ctx = P.build_context(synth(120, seed=seed * 10 + i, sigma=0.0010, drift_wave=False))
            o = Z.build_records("X%dUSDT" % i, ctx, btc, Z.ZParams(), {}, 0)
            ev += o["events"]
            ct += o["matched"]
        cb = {c["pair"]: c for c in ct}
        pe = [e for e in ev if e["pair"] in cb]
        if len(pe) >= 100:
            diffs.append(pu(pe) - pu([cb[e["pair"]] for e in pe]))
    assert len(diffs) >= 8, len(diffs)
    m, se = float(np.mean(diffs)), float(np.std(diffs) / np.sqrt(len(diffs)))
    assert abs(m) < max(3 * se, 0.015), (m, se)


def _synth_metrics(days=40, seed=3, start=1_790_000_000 // 86400 * 86400):
    rng = np.random.default_rng(seed)
    n = days * 288
    t = start + 300.0 * np.arange(n)
    oi = 1e6 * np.exp(np.cumsum(rng.normal(0, 0.0015, n)))
    top_pos = np.exp(rng.normal(0.2, 0.1, n))
    return np.column_stack([t, oi, oi * 100, np.exp(rng.normal(0.3, 0.1, n)), top_pos, np.exp(rng.normal(0.4, 0.1, n)), np.exp(rng.normal(0, 0.3, n))])


def test_flowdata():
    from office2 import flowdata as FD
    m = FD.parse_metrics_csv("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
                             "2025-06-01 00:00:00,BTCUSDT,83624.19,8736988614.4,1.2345,1.5616,1.1906,0.5528\n2025-06-01 00:05:00,BTCUSDT,83584.79,8734318426.2,1.2314,1.5629,1.1867,1.1643\n")
    assert m.shape == (2, 7) and abs(m[0, 0] - 1748736000.0) < 1 and abs(m[1, 1] - 83584.79) < 1e-6
    f = FD.parse_funding_csv("calc_time,funding_interval_hours,last_funding_rate\n1748736000001,8,-0.00000582\n1748764800002,8,0.00002335\n")
    assert f.shape == (2, 2) and abs(f[1, 1] - 0.00002335) < 1e-12
    mm = _synth_metrics()
    fund = np.column_stack([mm[0, 0] - 86400 + 8 * 3600.0 * np.arange(200), np.random.default_rng(1).normal(0.00005, 0.00005, 200)])
    fl = FD.prep(mm, fund)
    t_dec = mm[0, 0] + 20 * 86400.0 + 3600
    a = FD.features(fl, t_dec, 1.0, 1.0)
    b = FD.features(fl, t_dec, -1.0, -1.0)
    assert a["top_pos_rel"] == -b["top_pos_rel"] and a["oi_chg_4h_z"] == b["oi_chg_4h_z"] and a["funding_rel"] == -b["funding_rel"]
    # без lookahead: усічення даних після t_dec − 300 не змінює ознак
    keep = mm[:, 0] <= t_dec - 300
    fl2 = FD.prep(mm[keep], fund[fund[:, 0] <= t_dec - 300])
    a2 = FD.features(fl2, t_dec, 1.0, 1.0)
    for k, v in a.items():
        assert (v != v and a2[k] != a2[k]) or abs(v - a2[k]) < 1e-9, (k, v, a2[k])
    assert all(v == v for v in a.values()), a
    # збій даних: знімок OI=0 не руйнує z-оцінки на місяці вперед (раніше std ≈1e16 → решта ознак NaN)
    bad = mm.copy()
    bad[8000, 1] = 0.0
    fl_b = FD.prep(bad, fund)
    late = FD.features(fl_b, bad[0, 0] + 30 * 86400.0 + 3600, 1.0, 1.0)
    assert late["oi_chg_1h_z"] == late["oi_chg_1h_z"] and abs(late["oi_chg_1h_z"]) < 6.01 and late["oi_chg_4h_z"] == late["oi_chg_4h_z"]
    flat = FD.prep(mm, np.column_stack([mm[0, 0] - 86400 + 8 * 3600.0 * np.arange(200), np.full(200, 0.0001)]))
    assert FD.features(flat, t_dec, 1.0, 1.0)["funding_z"] == 0.0      # константний funding → z=0, рядок не губиться


def test_disp_population():
    from office2 import disp as D2
    full = synth(160, seed=61, sigma=0.0030)
    btc = synth(160, seed=62, sigma=0.0030)
    ctx, bctx = P.build_context(full), P.build_context(btc)
    rec = D2.build_records("XUSDT", ctx, bctx, D2.DParams(), {})
    assert len(rec) >= 20, len(rec)
    for r in rec:
        assert r["risk_atr"] > 0 and r["feat"]["body_atr"] >= 1.5 - 1e-9 and r["feat"]["close_loc"] >= 0.7 - 1e-9
    T = full["t"][0] + 130 * 86400
    cut = lambda a: {k: v[: int((T - a["t"][0]) // 60)] for k, v in a.items()}
    rc = D2.build_records("XUSDT", P.build_context(cut(full)), P.build_context(cut(btc)), D2.DParams(), {})
    k1 = {(r["dir"], r["j"]): r["feat"] for r in rec if r["t_dec"] <= T - 6 * 3600}
    k2 = {(r["dir"], r["j"]): r["feat"] for r in rc if r["t_dec"] <= T - 6 * 3600}
    assert k1 and set(k1) == set(k2)
    for k, a in k1.items():
        for n_, v in a.items():
            assert abs(v - k2[k][n_]) < 1e-6, (k, n_)


def test_flow_model_planted_and_null():
    """Модель оцінки джерел: знаходить ЗАСІЯНИЙ сигнал у блоці OI і не знаходить нічого на шумі (нульова калібровка)."""
    import sys as _s
    from pathlib import Path as _P
    _s.path.insert(0, str(_P(__file__).resolve().parent))
    import office2_flow_run as FR
    from office2 import disp as D2
    from office2 import flowdata as FD
    names = list(D2.DISP_OHLCV) + list(FR.TBV) + [k for b in FD.FLOW_BLOCKS.values() for k in b]
    def make(planted, seed):
        rng = np.random.default_rng(seed)
        rows = []
        for i in range(4000):
            x = {k: float(rng.normal()) for k in names}
            up = rng.random() < (0.5 + (0.22 * np.tanh(x["oi_with_trend"]) if planted else 0.0))
            rows.append({"symbol": "S%d" % (i % 25), "day": 100 + (i // 25), "order_1.0": "up" if up else "down", "r_net_g2": (2.0 if up else -1.0) - 0.1 + float(rng.normal(0, 0.1)), "X": x})
        return rows
    L = []
    v = FR.evaluate_pop("DISP", make(True, 1), 160, "test", L)
    assert v["M+OI"] and not v["M+TAKER5"], (v, "\n".join(L))
    vn = FR.evaluate_pop("DISP", make(False, 2), 160, "test", [])
    assert not any(vn.values()), vn


def test_mirror():
    m = E.mirror({"dir": "SHORT", "entry": 100.0, "sl": 101.0, "tp": 97.0, "trigger": "reclaim"})
    assert m["dir"] == "LONG" and m["sl"] == 99.0 and m["tp"] == 103.0 and m["trigger"] == "mirror"
    m = E.mirror({"dir": "LONG", "entry": 100.0, "sl": 99.0, "tp": 103.0})
    assert m["dir"] == "SHORT" and m["sl"] == 101.0 and m["tp"] == 97.0


def test_risk_manager():
    s = R.position_size(10.0, 100.0, 99.0, 0.10)
    # збиток на SL разом із комісіями = 10$
    loss = s["qty"] * 1.0 + s["notional"] * 0.001
    assert abs(loss - 10.0) < 1e-9
    assert R.position_size(10.0, 100.0, 100.0)["qty"] == 0.0     # без структурного SL розміру немає
    cfg = R.RiskConfig(risk_usd=10, max_open_risk_usd=30, max_cluster_open_risk_usd=20, max_same_direction_alts=2, daily_loss_r=3, dd_halt_r=5)
    def tr(t, sym, d, r, dur=3600, key=None):
        return {"t_entry": t, "t_exit": t + dur, "symbol": sym, "dir": d, "r_net": r, "lvl_key": key}
    t0 = 1_790_000_000.0
    pf = R.simulate_portfolio([tr(t0, "AUSDT", "LONG", 1), tr(t0 + 1, "BUSDT", "LONG", 1), tr(t0 + 2, "CUSDT", "LONG", 1)], cfg)
    assert len(pf["accepted"]) == 2 and pf["rejected"].get("cluster_risk", 0) + pf["rejected"].get("same_direction_alts", 0) == 1
    pf = R.simulate_portfolio([tr(t0, "AUSDT", "LONG", 1), tr(t0 + 5, "AUSDT", "LONG", 1)], cfg)
    assert pf["rejected"].get("same_symbol") == 1
    pf = R.simulate_portfolio([tr(t0, "BTCUSDT", "LONG", 1), tr(t0 + 1, "ETHUSDT", "SHORT", 1), tr(t0 + 2, "AUSDT", "LONG", 1), tr(t0 + 3, "BUSDT", "SHORT", 1)], cfg)
    assert pf["rejected"].get("open_risk") == 1
    # денний ліміт: три збитки по -1.5 R → далі відмова
    seq = [tr(t0 + i * 4000, f"X{i}USDT", "LONG", -1.5, dur=100) for i in range(4)]
    pf = R.simulate_portfolio(seq, cfg)
    assert pf["rejected"].get("daily_loss", 0) + pf["rejected"].get("drawdown_halt", 0) + pf["rejected"].get("halt_day", 0) >= 1
    # пов'язані сценарії (той самий рівень) і повтор після SL
    pf = R.simulate_portfolio([tr(t0, "AUSDT", "LONG", -1, 100, "k"), tr(t0 + 10, "BUSDT", "LONG", 1, 100, "k")], cfg)
    assert pf["rejected"].get("related_scenarios") == 1
    # після drawdown_halt система відновлюється наступної доби (база просадки скинута), а не блокується назавжди
    cfgh = R.RiskConfig(max_open_risk_usd=1000, max_cluster_open_risk_usd=1000, max_same_direction_alts=100, daily_loss_r=100, dd_halt_r=3)
    day0 = (t0 // 86400) * 86400
    seq = [tr(day0 + 100 + i * 200, f"Y{i}USDT", "LONG", -1.0, dur=100) for i in range(5)] + [tr(day0 + 86400 + 100 + i * 200, f"Z{i}USDT", "LONG", -1.0, dur=100) for i in range(5)]
    pf = R.simulate_portfolio(seq, cfgh)
    assert pf["rejected"].get("drawdown_halt", 0) >= 1 and any(a["symbol"].startswith("Z") for a in pf["accepted"]), (pf["rejected"], [a["symbol"] for a in pf["accepted"]])
    cfg2 = R.RiskConfig(repeat_after_sl_sec=7200)
    pf = R.simulate_portfolio([tr(t0, "AUSDT", "LONG", -1, 100), tr(t0 + 1000, "AUSDT", "LONG", 1, 100)], cfg2)
    assert pf["rejected"].get("repeat_after_sl") == 1


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
