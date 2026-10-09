#!/usr/bin/env python3
"""SMC replay: симуляція виходу, time-frozen (без майбутнього), підсумок Brain vs SMC, bootstrap, збереження. Офлайн на синтетиці; на реальних OHLCV — лише у worker (OFFICE2_SMC_REPLAY)."""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_bridge as OB  # noqa: E402
from office2 import brain as B  # noqa: E402
from office2.smc import fixtures as FX  # noqa: E402
from office2.smc import replay as RP  # noqa: E402
from scripts import replay_office2_public_data as PUB  # noqa: E402


def agg(m15, width):
    g = np.floor(m15["t"] / width).astype(np.int64)
    idx = np.flatnonzero(np.diff(g)) + 1
    st = np.r_[0, idx]
    en = np.r_[idx - 1, len(g) - 1]
    return {"t": (g[st] * width).astype(float), "o": m15["o"][st], "h": np.maximum.reduceat(m15["h"], st), "l": np.minimum.reduceat(m15["l"], st), "c": m15["c"][en], "v": np.ones(len(st)), "tbv": np.zeros(len(st))}


def series(n_pre=420):
    rs = np.random.RandomState(5)
    c = 105 + np.cumsum(rs.randn(n_pre) * 0.25)
    c = np.clip(c, 99, 111)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + 0.25
    l = np.minimum(o, c) - 0.25
    pre = FX.bars(list(zip(o, h, l, c)), t0=1_790_000_000.0)
    scen = FX.reversal_long()
    scen = {k: v.copy() for k, v in scen.items()}
    scen["t"] = float(pre["t"][-1]) + 900 * (1 + np.arange(len(scen["t"]), dtype=float))
    m15 = FX.concat(pre, scen)
    m15["tbv"] = np.zeros(len(m15["t"]))
    end_scen = float(m15["t"][-1]) + 900
    return m15, end_scen, len(scen["t"])


def arrays(m15):
    return {"m15": m15, "h4": agg(m15, 14400), "d1": agg(m15, 86400), "w1": agg(m15, 604800), "mn": None}


def test_simulate_outcomes_and_conservative_same_bar():
    b = FX.bars([(100, 101, 99, 100)] + [(100, 100.5, 99.5, 100.2)] * 3 + [(100.2, 103.5, 100.1, 103.0)])
    r = RP.simulate(b, 0, "LONG", 100.0, 98.0, 103.0, 1.5, 2.0)
    assert r["outcome"] == "TP1" and abs(r["r_gross"] - 1.5) < 1e-9 and r["r_net"] < 1.5 and r["bars"] == 4
    b2 = FX.bars([(100, 101, 99, 100), (100, 103.5, 97.5, 100)])                       # TP і SL в одному барі → SL
    assert RP.simulate(b2, 0, "LONG", 100.0, 98.0, 103.0, 1.5, 2.0)["outcome"] == "SL"
    b3 = FX.bars([(100, 101, 99, 100)] + [(100, 100.9, 99.2, 100.4)] * 5)
    r3 = RP.simulate(b3, 0, "LONG", 100.0, 98.0, 103.0, 1.5, 2.0)
    assert r3["outcome"] == "OPEN" and abs(r3["r_gross"] - 0.2) < 1e-9
    s = RP.simulate(FX.bars([(100, 101, 99, 100), (100, 100.5, 96.9, 97.5)]), 0, "SHORT", 100.0, 102.0, 97.0, 1.5, 2.0)
    assert s["outcome"] == "TP1"                                                         # SHORT: дзеркальна логіка


def test_execution_costs_delay_ttl_and_missed_entry_are_explicit():
    b = FX.bars([
        (100, 101, 99, 100),
        (100, 101, 99.5, 100.5),
        (101, 104.5, 100.5, 104),
        (104, 104.5, 103.5, 104),
    ])
    no_slip = RP.simulate(b, 0, "LONG", 100, 98, 104, 2, 2, fee_rt_pct=0.1, slippage_rt_bps=0)
    with_slip = RP.simulate(b, 0, "LONG", 100, 98, 104, 2, 2, fee_rt_pct=0.1, slippage_rt_bps=4)
    assert no_slip["outcome"] == with_slip["outcome"] == "TP1"
    assert round(no_slip["r_net"] - with_slip["r_net"], 6) == 0.02

    delayed = RP.simulate(b, 0, "LONG", 100, 98, 104, 2, 2, entry_delay_sec=900, entry_ttl_sec=1800)
    assert delayed["outcome"] == "TP1" and delayed["fill_entry"] == 101 and delayed["entry_delay_bars"] == 1
    assert round(delayed["r_gross"], 6) == 1.0 and delayed["risk_pct_at_fill"] > 0

    ttl = RP.simulate(b, 0, "LONG", 100, 98, 104, 2, 2, entry_delay_sec=901, entry_ttl_sec=900)
    assert ttl["outcome"] == "MISSED_ENTRY_TTL" and ttl["r_net"] is None

    touched = FX.bars([(100, 101, 99, 100), (100, 105, 99.5, 104), (104, 105, 103, 104)])
    missed = RP.simulate(touched, 0, "LONG", 100, 98, 104, 2, 2, entry_delay_sec=900, entry_ttl_sec=1800)
    assert missed["outcome"] == "MISSED_TP_BEFORE_ENTRY" and missed["fill_entry"] is None


def test_public_real_data_adapter_drops_forming_and_rejects_fixture():
    real_get = PUB._get
    rows = [
        {"time": 1000 + i * 900, "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i, "volume": 10 + i, "forming": i == 2}
        for i in range(3)
    ]
    try:
        def fake_get(url):
            tf = next(expected for _, (query, expected) in PUB.TF.items() if f"tf={query}" in url)
            return {"data_status": "DATA_OK", "fixture": False, "source": "binance_futures", "tf": tf, "candles": rows}
        PUB._get = fake_get
        arrs, provenance = PUB.fetch_arrays("https://readonly.example", "TESTUSDT")
        assert all(len(arrs[k]["t"]) == 2 for k in PUB.TF) and len(arrs["w1"]["t"]) == 1
        assert all(provenance[k]["source"] == "binance_futures" and provenance[k]["forming_dropped"] for k in PUB.TF)
        assert provenance["w1"]["source"] == "derived_from_binance_futures_d1"
        PUB._get = lambda url: {"data_status": "DATA_OK", "fixture": True, "source": "fixture", "tf": "15m", "candles": rows}
        try:
            PUB.fetch_arrays("https://readonly.example", "TESTUSDT")
            raise AssertionError("fixture must not be accepted as real replay data")
        except RuntimeError as exc:
            assert "real DATA_OK" in str(exc)
    finally:
        PUB._get = real_get


def test_replay_finds_smc_ready_exactly_when_sequence_completes_and_not_before():
    m15, end, n = series()
    orig = B.all_levels
    B.all_levels = lambda ctx, now: FX.REAL_LEVELS_LONG
    try:
        arrs = arrays(m15)
        full = RP.replay_arrays("TESTUSDT", arrs, end - 14 * 900, end, with_brain=False)
        ready = [e for e in full["events"] if e["source"] == "SMC"]
        assert ready and ready[0]["dir"] == "LONG" and ready[0]["ts_bar"] == int(end), [(e["ts_bar"], e["dir"]) for e in ready]
        early = RP.replay_arrays("TESTUSDT", arrs, end - 14 * 900, end - 3 * 900, with_brain=False)       # ті самі дані, але вікно до завершення моделі
        assert not [e for e in early["events"] if e["source"] == "SMC"]
        # бари ПІСЛЯ вікна не впливають: обрізаний масив дає той самий результат
        cut = {k: (v[:len(v) - 3] if hasattr(v, "__len__") and k in ("t", "o", "h", "l", "c", "v", "tbv") else v) for k, v in m15.items()}
        arrs2 = arrays(cut)
        early2 = RP.replay_arrays("TESTUSDT", arrs2, end - 14 * 900, end - 3 * 900, with_brain=False)
        assert [(e["ts_bar"], e["dir"]) for e in early2["events"]] == [(e["ts_bar"], e["dir"]) for e in early["events"]]
    finally:
        B.all_levels = orig


def test_summary_overlap_recall_and_caveats():
    mk = lambda src, d, t, out, r: {"source": src, "dir": d, "ts_bar": t, "symbol": "X", "model": "M", "key": f"{src}{t}", "entry": 1.0, "sl": 0.9, "tp1": 1.2, "sim": {"outcome": out, "r_net": r, "bars": 5, "r_gross": r}}  # noqa: E731
    runs = [{"symbol": "X", "bars": 100, "elapsed_s": 1, "events": [mk("BRAIN", "LONG", 1000, "TP1", 1.2), mk("SMC", "LONG", 1000 + 900, "SL", -1.1), mk("SMC", "SHORT", 90000, "TP1", 1.5)],
             "opportunities": [{"dir": "LONG", "ts_bar": 1000 + 900 * 3, "i": 3}, {"dir": "SHORT", "ts_bar": 500000, "i": 99}]}]
    s = RP.summarize(runs)
    assert s["engines"]["BRAIN"]["ready"] == 1 and s["engines"]["SMC"]["ready"] == 2
    assert {k: s["overlap"][k] for k in ("both", "only_brain", "only_smc")} == {"both": 1, "only_brain": 0, "only_smc": 1} and s["overlap"]["smc_minus_brain_bars"]["median"] == 1.0
    assert s["engines"]["SMC"]["outcomes"] == {"TP1": 1, "SL": 1, "OPEN": 0} and s["engines"]["SMC"]["r_net_ci95"] is None    # n<10 → без довірчого інтервалу
    assert s["engines"]["BRAIN"]["opportunities_caught"] == 1 and s["opportunities"] == 2
    assert any("не доказ прибутковості" in c for c in s["caveats"])
    ci1, ci2 = RP.bootstrap_ci(list(np.linspace(-1, 2, 30))), RP.bootstrap_ci(list(np.linspace(-1, 2, 30)))
    assert ci1 == ci2 and ci1[0] < ci1[1]


def test_store_and_reload():
    m15, end, n = series()
    orig = B.all_levels
    B.all_levels = lambda ctx, now: FX.REAL_LEVELS_LONG
    try:
        runs = [RP.replay_arrays("TESTUSDT", arrays(m15), end - 14 * 900, end, with_brain=False)]
        td = tempfile.mkdtemp()
        db = os.path.join(td, "o2.db")
        OB.init_office_db(db)
        RP.init_db(db)
        summ = RP.summarize(runs)
        k = RP.store(db, "t1", runs, summ)
        assert k >= 1 and OB._fetchone(db, "SELECT COUNT(*) FROM office2_smc_replay WHERE run_id='t1'")[0] == k
        assert OB._fetchone(db, "SELECT summary_json FROM office2_smc_replay_summary WHERE run_id='t1'")[0].count("caveats") == 1
        assert RP.store(db, "t1", runs, summ) == k and OB._fetchone(db, "SELECT COUNT(*) FROM office2_smc_replay WHERE run_id='t1'")[0] == k   # ідемпотентно
    finally:
        B.all_levels = orig


def test_late_sweep_split_with_independent_support_and_compute_timing():
    mk = lambda src, d, t, out, r, late=False: {"source": src, "dir": d, "ts_bar": t, "symbol": "X", "model": "M", "key": f"{src}{t}", "entry": 1.0, "sl": 0.9, "tp1": 1.2, "late": late, "ctx_class": "WITH_TREND",  # noqa: E731
                                                "sim": {"outcome": out, "r_net": r, "bars": 3, "r_gross": r}}
    runs = [{"symbol": "X", "bars": 10, "elapsed_s": 1, "opportunities": [], "timing": {"brain_ms": {"n": 5, "p50": 20.0, "p95": 40.0, "max": 55.0}, "smc_ms": {"n": 5, "p50": 100.0, "p95": 150.0, "max": 210.0}},
             "events": [mk("BRAIN", "LONG", 1000, "SL", -1.1, True), mk("SMC", "LONG", 1000, "SL", -1.1), mk("BRAIN", "SHORT", 90000, "TP1", 1.4, True), mk("BRAIN", "LONG", 200000, "TP1", 1.2)]}]
    s = RP.summarize(runs)
    ls = s["late_sweep"]
    assert ls["brain_late"]["ready"] == 2 and ls["brain_fresh"]["ready"] == 1 and ls["late_with_smc_support"]["ready"] == 1 and ls["late_without_smc_support"]["ready"] == 1
    assert s["engines"]["SMC"]["compute_ms_per_bar"]["max"] == 210.0 and s["engines"]["BRAIN"]["fast_sl_share"] == 1.0
    assert "не блокується" in ls["note"] or "не блокує" in ls["note"] or "READY не блокується" in ls["note"]


def test_run_spec_multi_job_with_fake_feed_and_invariants():
    m15, end, n = series()
    arrs = arrays(m15)

    class Feed:
        def klines(self, sym, tf, now, limit=None, start_ms=None, end_ms=None):
            key = {"15m": "m15", "4h": "h4", "1d": "d1", "1w": "w1", "1M": "mn"}[tf]
            a = arrs.get(key)
            if a is None:
                return None
            k = int(np.searchsorted(a["t"] * 1000.0 + {"m15": 900, "h4": 14400, "d1": 86400, "w1": 604800}[key] * 1000.0, end_ms + 1, side="right")) if end_ms else len(a["t"])
            return {kk: vv[max(0, k - (limit or k)):k] for kk, vv in a.items()}

    orig = B.all_levels
    B.all_levels = lambda ctx, now: FX.REAL_LEVELS_LONG
    td = tempfile.mkdtemp()
    db = os.path.join(td, "o2.db")
    OB.init_office_db(db)
    try:
        logs = []
        import time as _t
        real_time = _t.time
        _t.time = lambda: float(end + 96 * 900 + 900)                      # «зараз» = через 24 год після кінця вікна
        try:
            summ = RP.run_spec(db, Feed(), f"TESTUSDT@days=1@end={int(end)}@id=job1@throttle=0;TESTUSDT@days=1@end={int(end)}@id=job2@throttle=0@fee_rt_pct=0.08@slippage_rt_bps=6@entry_delay_sec=45@ttl_sec=3600", log=logs.append)
        finally:
            _t.time = real_time
        assert summ and summ["engines"]["SMC"]["ready"] >= 1 and "invariants_real_data" in summ and summ["invariants_real_data"]["TESTUSDT"]["n_violations"] == 0, summ and summ.get("invariants_real_data")
        assert summ["execution_assumptions"] == {"fee_rt_pct": 0.08, "slippage_rt_bps": 6.0, "entry_delay_sec": 45.0, "entry_ttl_sec": 3600.0, "bar_resolution_sec": 900}
        ids = {r[0] for r in OB._fetchall(db, "SELECT run_id FROM office2_smc_replay_summary")}
        assert ids == {"job1", "job2"}
    finally:
        B.all_levels = orig


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
