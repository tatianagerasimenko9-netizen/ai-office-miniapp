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
from office2.integration import validate_observation  # noqa: E402
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
        rows = OB._fetchall(db, "SELECT symbol, direction, model, state, ts_bar, payload_json FROM office2_smc_shadow")
        assert all(r[0] == "XUSDT" and r[4] == int(now) for r in rows)
        payloads = [json.loads(r[5]) for r in rows]
        assert payloads and all(p.get("observation") and not p.get("observation_errors") for p in payloads)
        assert all(validate_observation(p["observation"]) == [] for p in payloads)
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


def test_kill_switch_disables_everything():
    os.environ["OFFICE2_SMC"] = "0"
    try:
        td = tempfile.mkdtemp()
        db = os.path.join(td, "o2.db")
        OB.init_office_db(db)
        EN.init_db(db)
        assert OB._fetchone(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='office2_smc_shadow'") is None      # таблицю навіть не створено
        assert SH.snapshot_for("X", {}, 0.0, "LONG") is None and SH.shadow_stats(db) is None
        calls = []
        orig = SH.run_cycle
        SH.run_cycle = lambda *a, **k: calls.append(1)
        try:
            LV._spawn_smc(db, {"X": {}}, 1.0, {})
            time.sleep(0.15)
        finally:
            SH.run_cycle = orig
        assert not calls and not [t for t in threading.enumerate() if t.name == "office2-smc"]
        logs = []
        LV._log = (lambda orig_log: (lambda m: (logs.append(m), orig_log(m))))(LV._log)
        os.environ["OFFICE2_SMC_REPLAY"] = "BTCUSDT"
        LV._smc_replay_job(db, None)
        assert any("вимкнено" in m for m in logs)
    finally:
        os.environ["OFFICE2_SMC"] = "1"
        os.environ.pop("OFFICE2_SMC_REPLAY", None)


def test_brain_labels_late_sweep_without_blocking():
    from office2 import brain2 as B2
    from office2 import features as F
    from office2.smc import fixtures as FX
    import numpy as np
    base = [(105, 105.5, 104.5, 105.2)] * 40
    acc = [(101, 101.2, 97.5, 98.0)] * 4                                  # ≥3 закриття ЗА рівнем 100: рівень уже прийнято
    back = [(98, 102, 97.9, 101.5), (101.5, 102.5, 101, 102)] + [(102, 102.6, 101.6, 102.2)] * 4
    dip = [(102, 102.1, 99.2, 101.2)]                                     # новий «sweep» того ж рівня
    lv = [{"p": 100.0, "side": "low", "kind": "PDL", "strength": 1, "known": 0.0, "taken_ts": None}]
    for rows, want in ((base + acc + back + dip, "LATE_SWEEP"), (base + [(105, 105.5, 104.5, 105.2)] * 8 + dip[:0] + [(105, 105.2, 99.2, 101.2)], "FRESH_RAID")):
        b = FX.bars(rows)
        a = F.atr(b, 14)
        ev = B2._sweep_events(b, a, len(rows) - 1, lv, 1)
        assert ev and ev[0]["class"] == want, (want, ev and ev[0].get("class"), ev and ev[0].get("prior"))
    assert "повторний тест прийнятого рівня" in B2._ev_txt(ev_late := B2._sweep_events(FX.bars(base + acc + back + dip), F.atr(FX.bars(base + acc + back + dip), 14), len(base + acc + back + dip) - 1, lv, 1)[0], 1)


def test_divergence_feed_and_row_detail_with_overlay():
    orig = B.all_levels
    B.all_levels = lambda ctx, now: T.LEVELS
    try:
        db, ctxs, now = _run(True)
        SH.run_cycle(db, ctxs, now, {("XUSDT", "LONG"): "READY"}, log=lambda m: None)
        f = SH.feed(db, now=now + 600)
        br = [i for i in f["items"] if i["relation"] == "BRAIN_ONLY"]
        assert br and "Brain READY, а SMC на тому барі" in br[0]["why"] and br[0]["symbol"] == "XUSDT"
        generated = SH.row_detail(db, br[0]["id"])
        assert generated and generated["observation"] and not generated["observation_errors"]
        assert validate_observation(generated["observation"]) == []
        # додаємо SMC READY без Brain → SMC_ONLY і детальний рядок з overlay
        v = {"state": "READY", "stage": 7, "model": "REVERSAL", "steps": [{"step": "RAID", "ok": True, "value": "x", "j": 3, "t": 1.0}], "reason": "тест"}
        ov = {"v": 1, "items": [{"k": "line", "p": 1.0, "label": "SL", "role": "sl"}], "events": [], "steps": []}
        SH._put(OB._execute, db, int(now) - 7200, "YUSDT", "SHORT", "REVERSAL", v, "WAIT", 5.0, ov)
        f2 = SH.feed(db, now=now + 600)
        so = [i for i in f2["items"] if i["relation"] == "SMC_ONLY" and i["symbol"] == "YUSDT"]
        assert so and "Brain на цей момент: WAIT" in so[0]["why"]
        d = SH.row_detail(db, so[0]["id"])
        assert d and d["overlay"]["items"][0]["label"] == "SL" and d["role"].startswith("SHADOW")
        import office_mini_v2 as MV
        os.environ["OFFICE_DB_PATH"] = db
        os.environ.pop("DATABASE_URL", None)
        p = MV.smc_row_payload(so[0]["id"])
        assert p["ok"] and p["smc"]["state"] == "READY" and not MV.smc_row_payload("0|X|LONG|NOPE")["ok"]
        st = SH.shadow_stats(db, now=now + 600)
        assert "recent" in st and st["smc_ready"] >= 1
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
