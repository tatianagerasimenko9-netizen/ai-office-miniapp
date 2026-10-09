#!/usr/bin/env python3
"""SMC ↔ Brain v2.1: shadow не змінює рішень і не затримує цикл; знімок READY отримує display-only `smc`; помилка SMC не ламає READY; таблиця shadow; фонові виклики без черги."""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_office2_brain2 as T  # noqa: E402
import office_bridge as OB  # noqa: E402
from office2 import brain as B  # noqa: E402
from office2 import engine as EN  # noqa: E402
from office2 import live as LV  # noqa: E402
from office2.smc import shadow as SH  # noqa: E402

MC = {"btc_ret_1h": 0.1, "eth_ret_1h": 0.1, "breadth_up_1h": 0.5, "n_alts": 20}
REL = {"coin_ret_1h": 0.3, "rs_vs_btc_1h": 0.2, "rs_vs_btc_4h": 0.1}
ST = lambda b: {"price": float(b["c"][-1]), "ret_1h": 0.3, "ret_4h": 1.0, "ret_24h": 2.0, "atr15_pct": 0.3, "vol_regime_7d": 0.5, "pos_24h_range": 0.6}  # noqa: E731


def _run(smc_on: bool):
    os.environ["OFFICE2_SMC"] = "1" if smc_on else "0"
    c, seq = T.closes_long()
    td = tempfile.mkdtemp()
    db = os.path.join(td, "o2.db")
    OB.init_office_db(db)
    EN.init_db(db)
    ctxs = {}
    for upto in (seq["sweep"], seq["top"], seq["bear_in_zone"], seq["trigger"]):
        b, ctx = T.mk(c, upto)
        now = float(b["t"][-1] + 900)
        EN.step_symbol(db, "XUSDT", ctx, ST(b), MC, REL, now, None)
        ctxs, last_now = {"XUSDT": ctx}, now
    return db, ctxs, last_now


def _norm(snap):
    s = dict(snap)
    for k in ("smc", "latency", "emitted_wall_ts"):
        s.pop(k, None)
    return json.dumps(s, sort_keys=True, default=str)


def test_smc_does_not_change_brain_decision():
    orig = B.all_levels
    B.all_levels = lambda ctx, now: T.LEVELS
    try:
        db1, _, _ = _run(True)
        db0, _, _ = _run(False)
        r1 = OB._fetchall(db1, "SELECT scenario_id, state, reason FROM office2_live_scenario ORDER BY scenario_id")
        r0 = OB._fetchall(db0, "SELECT scenario_id, state, reason FROM office2_live_scenario ORDER BY scenario_id")
        assert r1 == r0 and any(x[1] == "READY" for x in r1)
        s1 = json.loads(OB._fetchone(db1, "SELECT snapshot_json FROM office2_live_signal")[0])
        s0 = json.loads(OB._fetchone(db0, "SELECT snapshot_json FROM office2_live_signal")[0])
        assert _norm(s1) == _norm(s0)                                                   # знімок Brain побітово той самий; різниця лише display-поле smc
        assert s0["smc"] is None and s1["smc"] and s1["smc"]["role"].startswith("SHADOW") and "state" in s1["smc"] and s1["smc"]["timing_ms"] >= 0
    finally:
        B.all_levels = orig
        os.environ["OFFICE2_SMC"] = "1"


def test_smc_failure_never_breaks_ready():
    orig, orig_a = B.all_levels, SH.analyze_ctx
    B.all_levels = lambda ctx, now: T.LEVELS

    def boom(*a, **k):
        raise RuntimeError("smc boom")
    SH.analyze_ctx = boom
    try:
        db, _, _ = _run(True)
        snap = json.loads(OB._fetchone(db, "SELECT snapshot_json FROM office2_live_signal")[0])
        assert snap["smc"] is None                                                       # знімок створено, поле порожнє
        assert SH.stats()["errors"] >= 1
    finally:
        B.all_levels, SH.analyze_ctx = orig, orig_a


def test_shadow_table_rows_idempotent_and_no_lookahead():
    orig = B.all_levels
    B.all_levels = lambda ctx, now: T.LEVELS
    try:
        db, ctxs, now = _run(True)
        out = SH.run_cycle(db, ctxs, now, {("XUSDT", "LONG"): "READY"}, log=lambda m: None)
        n1 = OB._fetchone(db, "SELECT COUNT(*) FROM office2_smc_shadow")[0]
        out2 = SH.run_cycle(db, ctxs, now, None, log=lambda m: None)
        n2 = OB._fetchone(db, "SELECT COUNT(*) FROM office2_smc_shadow")[0]
        assert n1 == n2                                                                  # повторний прохід того ж бару не дублює
        assert SH.stats()["cycles"] >= 2 and out["ms"] >= 0
        rows = OB._fetchall(db, "SELECT symbol, direction, model, state, ts_bar FROM office2_smc_shadow")
        assert all(r[0] == "XUSDT" and r[4] == int(now) for r in rows)
    finally:
        B.all_levels = orig


def test_spawn_is_nonblocking_and_skips_when_busy():
    calls = []
    orig = SH.run_cycle

    def slow(db, ctxs, now, bs, log=print):
        calls.append(now)
        time.sleep(0.4)
        return {}
    SH.run_cycle = slow
    try:
        t0 = time.time()
        LV._spawn_smc("nodb", {"X": {"m15": None}}, 1.0, {})
        LV._spawn_smc("nodb", {"X": {"m15": None}}, 2.0, {})                              # попередній прохід ще йде → пропуск, без черги
        assert time.time() - t0 < 0.2, "виклик має повертатись одразу"
        time.sleep(0.7)
        assert calls == [1.0], calls
        os.environ["OFFICE2_SMC"] = "0"
        LV._spawn_smc("nodb", {"X": {"m15": None}}, 3.0, {})
        time.sleep(0.1)
        assert calls == [1.0]
    finally:
        SH.run_cycle = orig
        os.environ["OFFICE2_SMC"] = "1"


def test_shadow_stats_for_journal():
    orig = B.all_levels
    B.all_levels = lambda ctx, now: T.LEVELS
    try:
        db, ctxs, now = _run(True)
        SH.run_cycle(db, ctxs, now, None, log=lambda m: None)
        st = SH.shadow_stats(db, now=now + 3600)
        assert st and st["brain_ready"] >= 1 and set(st) >= {"rows", "states", "smc_ready", "brain_ready_confirmed_by_smc", "smc_ready_only", "note", "runtime"}
        assert "не впливає на READY" in st["note"]
        from office2 import stats as ST
        assert "smc" in ST.collect(db)
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
