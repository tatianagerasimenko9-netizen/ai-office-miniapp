#!/usr/bin/env python3
"""Learning-контур: облік R/$ при ризику $10, класифікатор, контрфактуальні фільтри (ціна пропущених виграшів), walk-forward, завантаження з БД. Без мережі."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.learning import classify as CL
from office2.learning import compare as CP
from office2.learning import costs as C
from office2.learning import job as J
from office2.learning import pnl as P
from office2.learning import report as R
from office2.learning import trades as T
from office2.learning.sessions import session_of

FIX = Path(__file__).resolve().parent.parent / "fixtures/learning/office2_delivered_2026-10-10.json"


def tr(first, r1=2.0, stop=1.0, **kw):
    ms = [["ENTRY", 100.0]] + ([["TP1", 200.0]] if first == "TP1" else [["SL", 160.0]] if first == "SL" else [])
    row = {"sid": kw.pop("sid", f"S{first}{r1}{stop}{len(kw)}"), "symbol": kw.pop("symbol", "XUSDT"), "direction": kw.pop("direction", "LONG"), "created_ts": kw.pop("created_ts", 1_790_000_000.0),
           "delivered_ts": kw.pop("delivered_ts", 1_790_000_030.0), "r1": r1, "r2": r1 * 2, "r3": r1 * 3, "stop_pct": stop, "kind": "SWEEP_SEQ", "milestones": ms}
    row.update(kw)
    return T.from_office2(row)


def test_costs_scale_with_stop():
    assert abs(C.cost_r(1.0) - 0.15) < 1e-9 and abs(C.cost_r(0.3) - 0.5) < 1e-9
    assert C.cost_r(None) is None and C.cost_r(0) is None


def test_pnl_model_a_usd():
    w, l = tr("TP1", r1=2.0, stop=1.0), tr("SL", r1=2.0, stop=1.0, sid="L")
    s = P.summarize([w, l], "A")
    assert s["resolved"] == 2 and abs(s["sum_r_net"] - ((2 - 0.15) + (-1 - 0.15))) < 1e-6
    assert abs(s["usd_net"] - 7.0) < 1e-6 and abs(s["usd_costs"] - 3.0) < 1e-6 and abs(s["usd_gross"] - 10.0) < 1e-6


def test_unfilled_and_open_not_counted():
    nf = T.from_office2({"sid": "N", "symbol": "X", "direction": "LONG", "created_ts": 1.0, "r1": 2, "stop_pct": 1, "milestones": []})
    op = T.from_office2({"sid": "O", "symbol": "X", "direction": "LONG", "created_ts": 1.0, "r1": 2, "stop_pct": 1, "milestones": [["ENTRY", 5]]})
    assert nf["first"] == "NOFILL" and op["first"] == "OPEN"
    s = P.summarize([nf, op], "A")
    assert s["resolved"] == 0 and s["usd_net"] == 0 and s["excluded_unresolved"] == 2


def test_model_b_partial_and_breakeven():
    t = tr("TP1", r1=2.0, stop=1.0)
    t["eventually_tp2"] = True
    assert abs(P.net(t, "B") - (0.5 * 2.0 + 0.5 * 4.0 - 0.15)) < 1e-9
    t2 = tr("TP1", r1=2.0, stop=1.0)
    t2["eventually_sl"] = True                 # решта вийшла по беззбитку
    assert abs(P.net(t2, "B") - (1.0 - 0.15)) < 1e-9
    assert P.net(tr("TP1"), "B") is None      # решта ще відкрита — не зараховується


def test_classifier_definitions_and_undetermined():
    lag = tr("SL", delivered_ts=1_790_000_300.0, sid="lag")
    assert "DELIVERY_LAG" in CL.flags(lag)
    cheap = tr("SL", stop=0.4, sid="cheap")                       # cost_r = 0.375 ≥ 0.25
    assert "COST_HEAVY" in CL.flags(cheap)
    lowrr = tr("TP1", r1=1.1, stop=1.0, sid="lowrr")              # 1.1−0.15 < 1
    assert "LOW_RR" in CL.flags(lowrr)
    htf = tr("SL", align_against=3, align_for=1, sid="htf")
    assert "HTF_CONFLICT" in CL.flags(htf)
    clean = tr("SL", sid="clean", align_against=0, align_for=3, level_strength=3, r1=3.0)
    clean["sl_after_entry_s"] = 5000.0
    assert CL.classify(clean)["flags"] == ["UNDETERMINED"]        # причину не вигадуємо
    stale = T.from_office2({"sid": "st", "symbol": "X", "direction": "SHORT", "created_ts": 1.0, "delivered_ts": 2.0, "r1": 2, "stop_pct": 1, "milestones": [["ENTRY", 100], ["SL", 101]]})
    assert "STALE_AT_DELIVERY" in CL.flags(stale)


def test_opposite_exposure_and_duplicate():
    a = tr("SL", sid="a", direction="SHORT", created_ts=1_790_000_000.0)
    a["milestones"]["SL"] = 1_790_050_000.0
    b = tr("TP1", sid="b", direction="LONG", created_ts=1_790_010_000.0)
    c = tr("SL", sid="c", direction="SHORT", created_ts=1_790_003_000.0, level_kind="PDH")
    a["level_kind"] = "PDH"
    allt = [a, b, c]
    assert "OPPOSITE_EXPOSURE" in CL.flags(b, allt)
    assert "DUPLICATE_THESIS" in CL.flags(c, allt)
    assert "OPPOSITE_EXPOSURE" not in CL.flags(a, [a])


def test_filter_effect_counts_lost_winners():
    ts = [tr("SL", sid=f"l{i}", delivered_ts=1_790_000_500.0) for i in range(4)] + [tr("TP1", sid=f"w{i}", delivered_ts=1_790_000_500.0) for i in range(3)] + [tr("TP1", sid="ok")]
    for t in ts:
        t["flags"] = CL.flags(t)
    e = CP.filter_effect(ts, lambda t: "DELIVERY_LAG" in t["flags"])
    assert e["skipped"] == 7 and e["losses_avoided"] == 4 and e["wins_lost"] == 3 and e["trades_after"] == 1
    assert abs(e["delta_r"] - (e["sum_r_after"] - e["sum_r_before"])) < 1e-9


def test_small_samples_are_insufficient_not_confirmed():
    ts = [tr("SL", sid=f"l{i}", delivered_ts=1_790_000_500.0, created_ts=1_790_000_000.0 + i) for i in range(5)] + [tr("TP1", sid=f"w{i}", created_ts=1_790_000_100.0 + i) for i in range(5)]
    c = CP.contrast(ts, lambda t: t["lag_s"] > 120)
    assert c["verdict"] == "INSUFFICIENT"
    for t in ts:
        t["flags"] = CL.flags(t)
    assert CP.walk_forward(ts, lambda t: "DELIVERY_LAG" in t["flags"])["status"] == "INSUFFICIENT"


def test_confirmed_requires_both_periods_same_sign():
    import random
    rnd = random.Random(1)
    ts = []
    for i in range(80):
        bad = i % 2 == 0
        ts.append(tr("SL" if (bad or rnd.random() < 0.15) else "TP1", sid=f"x{i}", created_ts=1_790_000_000.0 + i * 600, delivered_ts=1_790_000_000.0 + i * 600 + (300 if bad else 30)))
    for t in ts:
        t["flags"] = CL.flags(t)
    wf = CP.walk_forward(ts, lambda t: "DELIVERY_LAG" in t["flags"])
    assert wf["status"] == "CONFIRMED_ON_BOTH" and wf["train"]["delta_r"] > 0 and wf["test"]["delta_r"] > 0
    c = CP.contrast(ts, lambda t: "DELIVERY_LAG" in t["flags"])
    assert c["verdict"] == "SUPPORTED_HARMFUL"


def _m15(rows):
    import numpy as np
    a = np.array(rows, dtype=float)
    n = len(a)
    return {"t": 1_790_000_000.0 + 900 * np.arange(n), "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3], "v": np.ones(n), "tbv": np.ones(n)}


def test_counterfactual_limit_and_delay_rules():
    from office2.learning import counterfactual as CF
    flat = [(100, 100.2, 99.8, 100)] * 30
    # рішення на барі 29; далі ціна одразу йде до TP без ретесту → лімітний вхід пропущено, поточне правило «заробило» (вхід за планом)
    up = _m15(flat + [(100.3, 103.0, 100.3, 102.8)] + [(102.8, 103.0, 102.5, 102.9)] * 10)
    ev = {"dir": "LONG", "entry": 100.0, "sl": 99.0, "tp1": 102.0, "r_tp1": 2.0, "risk_pct": 1.0, "source": "BRAIN", "ts_bar": int(up["t"][29] + 900), "i": 29, "symbol": "X"}
    r = CF.per_event([ev], up)[0]["variants"]
    assert r["V0_current"]["outcome"] == "TP1"
    assert r["V6_limit_retest"]["outcome"] == "MISSED_TP_BEFORE_ENTRY"          # ціна не повернулась до входу — виграш за лімітним правилом втрачено
    assert r["V1_delay_15m"]["outcome"].startswith("MISSED") or r["V1_delay_15m"]["outcome"] in ("TP1", "SL")
    agg = CF.aggregate([dict(per_event_row=0, symbol="X", source="BRAIN", dir="LONG", ts_bar=1, session="ASIA", variants=r)])
    assert agg["by_source"]["BRAIN"]["V6_limit_retest"]["missed"] == 1 and agg["by_source"]["BRAIN"]["V0_current"]["scored"] == 1


def test_paired_marks_stable_only_with_consistent_halves():
    from office2.learning import counterfactual as CF
    rows = []
    for i in range(60):
        base = {"outcome": "SL", "r_net": -1.0, "bars": 3}
        better = {"outcome": "TP1", "r_net": 0.8, "bars": 5} if i % 3 == 0 else {"outcome": "SL", "r_net": -1.0, "bars": 3}
        v = {k: dict(base) for k in CF.VARIANTS}
        v["V5_sl_plus_1.0atr"] = better
        v["V3_delay_60m"] = {"outcome": "MISSED_SL_BEFORE_ENTRY", "r_net": None, "bars": 0}
        rows.append({"source": "BRAIN", "ts_bar": 1000 + i, "symbol": "X", "dir": "LONG", "variants": v})
    p = CF.paired(rows, "BRAIN")
    assert p["V5_sl_plus_1.0atr"]["status"] == "STABLE" and p["V5_sl_plus_1.0atr"]["mean_delta_r"] > 0
    assert p["V3_delay_60m"]["mean_delta_r"] == 1.0                       # пропуск збиткових входів = 0R замість −1R
    assert CF.paired(rows[:10], "BRAIN")["V5_sl_plus_1.0atr"]["status"] == "INSUFFICIENT"


def test_old_lev_model_b_not_applicable_and_filter_table():
    from office2.learning import counterfactual as CF
    plan = {"scenario_id": "S", "symbol": "A", "direction": "LONG", "tf": "H1", "entry": 100.0, "sl": 99.0, "tp1": 103.0, "confirmed_ts": 1_790_000_000.0}
    t = T.from_old_lev(plan, {"outcome": "TP2", "filled": True, "rejected": False})
    assert P.net(t, "B") is None and P.net(t, "A") is not None
    mk = lambda i, oc, rp: {"source": "BRAIN", "ts_bar": i, "dir": "LONG", "risk_pct": rp, "session": "ASIA", "variants": {"V0_current": {"outcome": oc, "r_net": 1.0 if oc == "TP1" else -1.0}}}   # noqa: E731
    rows = [mk(i, "SL", 0.3) for i in range(6)] + [mk(10 + i, "TP1", 2.0) for i in range(4)]
    ft = CF.filter_table(rows, "BRAIN")["COST_HEAVY"]["all"]
    assert ft["skipped"] == 6 and ft["sl_avoided"] == 6 and ft["tp1_lost"] == 0 and abs(ft["delta_r"] - 6.0) < 1e-9 and abs(ft["delta_usd_at_10"] - 60.0) < 1e-9


def test_sessions_dst_aware():
    # 2026-07-01 07:30Z = 08:30 Лондон (літо) → LONDON; 2026-01-15 07:30Z = 07:30 Лондон (зима) → PRE_LONDON
    import datetime as dt
    s = dt.datetime(2026, 7, 1, 7, 30, tzinfo=dt.timezone.utc).timestamp()
    w = dt.datetime(2026, 1, 15, 7, 30, tzinfo=dt.timezone.utc).timestamp()
    assert session_of(s)["session"] == "LONDON" and session_of(w)["session"] == "PRE_LONDON"
    assert session_of(dt.datetime(2026, 7, 1, 14, 0, tzinfo=dt.timezone.utc).timestamp())["session"] == "LONDON_NY_OVERLAP"


def test_real_snapshot_regression():
    """Знімок production 10.10.2026: 33 доставлені. Числа зафіксовано, щоб зміна обліку не проходила непоміченою."""
    ts = [T.from_office2(r) for r in json.load(open(FIX))["signals"]]
    assert len(ts) == 33
    a = P.summarize(ts, "A")
    assert (a["resolved"], a["wins"]) == (30, 14) and abs(a["usd_net"] - 18.2) < 0.2 and abs(a["usd_costs"] - 64.1) < 0.2
    rep = R.build(ts)
    assert rep["first_result"] == {"TP1": 14, "SL": 16, "OPEN": 3}
    assert all(v["walk_forward"]["status"] == "INSUFFICIENT" for v in rep["filters"].values()), "на 30 угодах жодне правило не може бути підтверджене"


def test_old_lev_mapping():
    plan = {"scenario_id": "S", "symbol": "A", "direction": "LONG", "tf": "H1", "entry": 100.0, "sl": 99.0, "tp1": 103.0, "confirmed_ts": 1_790_000_000.0}
    assert T.from_old_lev(plan, {"outcome": "STOP", "filled": True, "rejected": False})["first"] == "SL"
    t = T.from_old_lev(plan, {"outcome": "TP2", "filled": True, "rejected": True})
    assert t["first"] == "TP1" and abs(t["r1"] - 3.0) < 1e-9 and t["engine"] == "old_lev" and not t["delivered_to_user"]
    assert T.from_old_lev(plan, {"outcome": "OPEN_TIMEOUT", "filled": True})["first"] == "OPEN"
    assert T.from_old_lev(dict(plan, sl=100.0), {"outcome": "STOP", "filled": True}) is None


def test_job_from_db_roundtrip():
    import office_bridge as OB
    from office2 import engine as EN
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "l.db")
        OB.init_office_db(db)
        EN.init_db(db)
        snap = {"thesis": {"kind": "SWEEP_SEQ", "quality": {"first_target_r": 2.0, "risk_atr15": 2.0}, "sizing": {"stop_pct": 1.0}, "targets": [{"r": 2.0}, {"r": 3.0}, {"r": 4.0}], "level": {"kind": "H4SW", "strength": 2}},
                "alignment_summary": {"against": 1, "for": 3}}
        OB._execute(db, "INSERT INTO office2_live_signal(scenario_id, symbol, direction, created_ts, valid_until_ts, status, delivered_ts, snapshot_json, version) VALUES (?,?,?,?,?,?,?,?,?)",
                    ("O2|a|1", "AAAUSDT", "LONG", 1_790_000_000.0, 1_790_021_600.0, "DELIVERED", 1_790_000_040.0, json.dumps(snap), "t"))
        OB.log_event(db, "SCENARIO_MILESTONE", {"level": "ENTRY", "sent_ts": 1_790_000_050.0}, "O2|a|1")
        OB.log_event(db, "SCENARIO_MILESTONE", {"level": "TP1", "sent_ts": 1_790_003_000.0}, "O2|a|1")
        OB.log_event(db, "SIGNAL_PLAN", {"scenario_id": "SCN|B", "symbol": "BBB", "direction": "SHORT", "tf": "H1", "entry": 10.0, "sl": 10.2, "tp1": 9.6, "confirmed_ts": 1_790_000_100.0}, "SCN|B")
        OB.log_event(db, "SIGNAL_RESULT", {"scenario_id": "SCN|B", "outcome": "STOP", "filled": True, "rejected": False}, "SCN|B")
        done = J.run_once(db, now=1_790_100_000.0, log=lambda m: None)
        assert done == {"office2": 1, "old_lev_delivered": 1}, done
        row = OB._fetchone(db, "SELECT n_trades, report_json FROM office2_learning_report WHERE scope = 'office2'")
        rep = json.loads(row[1])
        assert row[0] == 1 and rep["pnl"]["A"]["resolved"] == 1 and rep["pnl"]["A"]["wins"] == 1
        J.run_once(db, now=1_790_100_000.0, log=lambda m: None)           # той самий ts_epoch → ідемпотентно
        assert OB._fetchone(db, "SELECT COUNT(*) FROM office2_learning_report")[0] == 2


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
    print("OK")
