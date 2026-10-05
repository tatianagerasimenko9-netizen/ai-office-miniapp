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
