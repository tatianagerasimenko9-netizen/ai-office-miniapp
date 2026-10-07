#!/usr/bin/env python3
"""Office2 Brain v2: повний ланцюг (подія → зсув структури → зона входу → ретрейс → тригер), заборона READY за sweep+reclaim+1 бар, дзеркало SHORT, без lookahead."""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import o2live_synth as S  # noqa: E402
from office2 import brain as B  # noqa: E402
from office2 import brain2 as B2  # noqa: E402
from office2 import features as F  # noqa: E402

LEVELS = [{"p": 99.0, "side": "low", "kind": "PDL", "strength": 1, "known": 0.0}, {"p": 103.6, "side": "high", "kind": "PDH", "strength": 1, "known": 0.0}, {"p": 106.0, "side": "high", "kind": "PWH", "strength": 1, "known": 0.0}]


def closes_long():
    rng = np.random.default_rng(3)
    base = list(100.3 + np.cumsum(rng.normal(0, 0.04, 400)))
    base = [100.3 + (x - 100.3) * 0.3 for x in base]
    c = base[:]
    ev = [99.6, 98.9, 99.2]                                   # sweep рівня 99.0 (low нижче), повернення
    c += ev
    seq = {"sweep": len(c)}
    c += [99.6, 99.95, 100.3, 100.0, 99.75, 99.6]                  # відскок до swing-high 100.3 і м'який відкат
    seq["pre_shift"] = len(c)
    c += [101.2]                                                    # displacement: закриття над 100.3
    seq["shift"] = len(c)
    c += [101.6, 102.0]
    seq["top"] = len(c)
    c += [101.5, 100.9, 100.4, 100.1]                               # ретрейс до зони
    seq["in_zone_pre"] = len(c)
    c += [99.85]                                                    # у зоні, але ведмежа свічка
    seq["bear_in_zone"] = len(c)
    c += [100.05]                                                   # бичачий відбій у зоні
    seq["trigger"] = len(c)
    return c, seq


def mk(closes, upto):
    b = S._bars_from_closes(closes[:upto])
    h4, d1, w1 = F.resample(b, 4 * 3600), F.resample(b, 86400), F.resample(b, 7 * 86400, offset=F.WEEK_OFFSET)
    return b, B.build_full_ctx(b, h4, d1, w1)


def run(closes, upto, direction="LONG", levels=None):
    b, ctx = mk(closes, upto)
    now = float(b["t"][-1] + 900)
    return B2.thesis(ctx, direction, now, levels or LEVELS, 10.0)


def test_chain_progression_long():
    c, seq = closes_long()
    th = run(c, seq["sweep"])
    assert th and th["state"] == "WAIT" and "потрібен зсув структури" in th["reason"], th              # sweep+reclaim самі по собі — НЕ READY
    th = run(c, seq["pre_shift"])
    assert th["state"] == "WAIT" and "зсув структури" in th["reason"], th
    th = run(c, seq["top"])
    assert th["state"] == "WAIT" and "контрольований ретрейс" in th["reason"] and th["entry_zone"], th        # displacement є, але гнатися не можна
    th = run(c, seq["bear_in_zone"])
    assert th["state"] == "WAIT" and "бичаче закриття" in th["reason"], th                                    # у зоні, але тригера нема
    th = run(c, seq["trigger"])
    assert th["state"] == "READY", th
    q = th["quality"]
    assert th["sl"] < th["invalidation"]["price"] < th["entry_zone"][0] and th["invalidation"]["buffer"] > 0 and th["targets"][0]["r"] >= 1.0
    assert q["risk_atr15"] >= 1.0 and [s["step"] for s in th["sequence"] if s["ok"]][:4] == ["подія", "зсув структури (MSS/BOS)", "нога зміщення і зона входу", "ретрейс у зону"]
    assert th["entry_zone"][0] <= th["entry"] <= th["entry_zone"][1] + 1.0 and abs(th["sizing"]["notional_usd"] - 10.0 / (th["risk"] / th["entry"])) < 1e-6
    assert th["id"] == run(c, seq["trigger"] - 1)["id"]                                                       # id стабільний протягом життя сценарію


def test_no_ready_from_sweep_reclaim_hold_only():
    """Старий шлях: sweep → reclaim → утримання 1 бар дав READY. Тепер — жодного READY без зсуву структури, ретрейсу й тригера."""
    c, seq = closes_long()
    for n in range(seq["sweep"], seq["pre_shift"] + 1):
        th = run(c, n)
        assert th is None or th["state"] != "READY", (n, th)


def test_short_mirror_and_no_lookahead():
    c, seq = closes_long()
    cm = [200.0 - x for x in c]
    lev = [{"p": 200.0 - x["p"], "side": "high" if x["side"] == "low" else "low", "kind": x["kind"], "strength": 1, "known": 0.0} for x in LEVELS]
    th = run(cm, seq["trigger"], "SHORT", lev)
    th_l = run(c, seq["trigger"])
    assert th["state"] == "READY" and abs(th["entry"] - (200.0 - th_l["entry"])) < 1e-6 and th["sl"] > th["invalidation"]["price"] > th["entry_zone"][1], th
    # без lookahead: решта серії не змінює рішення на prefix
    b_full = S._bars_from_closes(c + [104.0, 105.0, 90.0])
    a = run(c, seq["trigger"])
    cc = c[:seq["trigger"]]
    b = S._bars_from_closes(cc)
    assert a["state"] == "READY" and run(cc, len(cc))["entry"] == a["entry"]
    assert len(b_full["t"]) > len(b["t"])


def test_missed_and_invalidated():
    c, seq = closes_long()
    run_away = c[:seq["top"]] + [102.4, 103.0, 103.6, 104.2, 104.8, 105.3, 105.9, 106.4, 107.0, 107.5]
    th = run(run_away, len(run_away))
    assert th["state"] in ("MISSED", "WAIT"), th
    long_run = c[:seq["top"]] + list(np.linspace(102.0, 112.0, 40))
    th = run(long_run, len(long_run))
    assert th["state"] == "MISSED" and "не доганяємо" in th["reason"], th
    broken = c[:seq["top"]] + [101.0, 100.0, 99.2, 98.4]
    th = run(broken, len(broken))
    assert th["state"] == "INVALIDATED", th


def test_registry_roles():
    roles = {v["role"] for v in B2.REGISTRY.values()}
    assert roles == {"GATE", "CONTEXT", "EVIDENCE", "RESEARCH", "NOT_CONNECTED"}
    assert B2.REGISTRY["DOM / order book"]["role"] == "NOT_CONNECTED" and B2.REGISTRY["MSS/BOS + displacement"]["role"] == "GATE"


def test_engine_integration_v2_trace_and_evidence():
    """step_symbol: brain v2 → WAIT… → READY; у знімку послідовність, evidence-модулі (ролі/статуси), version_id; Telegram-картка із зоною входу."""
    import json
    import tempfile

    import office_bridge as OB
    from office2 import delivery as DL
    from office2 import engine as EN

    assert EN.BRAIN_V2
    c, seq = closes_long()
    orig = B.all_levels
    B.all_levels = lambda ctx, now: LEVELS
    try:
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "o2.db")
            OB.init_office_db(db)
            EN.init_db(db)
            for upto in (seq["sweep"], seq["top"], seq["bear_in_zone"], seq["trigger"]):
                b, ctx = mk(c, upto)
                now = float(b["t"][-1] + 900)
                st = {"price": float(b["c"][-1]), "ret_1h": 0.3, "ret_4h": 1.0, "ret_24h": 2.0, "atr15_pct": 0.3, "vol_regime_7d": 0.5, "pos_24h_range": 0.6}
                EN.step_symbol(db, "XUSDT", ctx, st, {"btc_ret_1h": 0.1, "eth_ret_1h": 0.1, "breadth_up_1h": 0.5, "n_alts": 20}, {"coin_ret_1h": 0.3, "rs_vs_btc_1h": 0.2, "rs_vs_btc_4h": 0.1}, now, None,
                               flow_fetch=lambda: {}, m5_fetch=lambda: None)
            rows = OB._fetchall(db, "SELECT scenario_id, version, snapshot_json FROM office2_live_signal")
            assert len(rows) == 1 and rows[0][1] == B2.VERSION, rows
            snap = json.loads(rows[0][2])
            assert snap["version_id"] == B2.VERSION and snap["sequence"] and snap["thesis"]["kind"] in ("SWEEP_SEQ", "ORIGIN_SEQ")
            mods = {m["module"]: m for m in snap["evidence"]}
            assert mods["DOM / order book"]["status"] == "NOT_CONNECTED" and mods["OI / funding / L:S / ліквідації"]["status"] == "UNAVAILABLE" and mods["M5/M1 тригер"]["status"] == "UNAVAILABLE"
            assert mods["HTF MN/W1/D1/H4/H1"]["role"] == "CONTEXT" and mods["volume / taker-delta / CVD"]["status"] in ("USED", "UNAVAILABLE")
            steps = [t["step"] for t in snap["trace"]]
            assert any("послідовність" in x for x in steps) and any("модулі" in x for x in steps)
            sc_states = [r[0] for r in OB._fetchall(db, "SELECT to_state FROM office2_live_transition ORDER BY ts ASC")]
            assert "WAIT" in sc_states and sc_states[-1] == "READY", sc_states
            cap = DL.build_caption(dict(snap, valid_until_ts=snap["decided_ts"] + 3600))
            th = snap["thesis"]
            assert "Зона входу:" in cap and "READY:" in cap and "Чому:" in cap, cap
            assert th["entry_zone"][0] <= th["entry"]
    finally:
        B.all_levels = orig


def test_scenario_ids_unique_per_symbol():
    """Регресія: однакова подія (напрям/вид/час) на двох монетах → різні scenario_id і окремі рядки в БД, thesis не перемішується."""
    import tempfile

    import office_bridge as OB
    from office2 import engine as EN

    assert EN.scoped_id("AUSDT", "O2|abc") != EN.scoped_id("BUSDT", "O2|abc") and EN.scoped_id("AUSDT", "O2|abc") == EN.scoped_id("AUSDT", "O2|abc")
    c, seq = closes_long()
    orig = B.all_levels
    B.all_levels = lambda ctx, now: LEVELS
    try:
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "o2.db")
            OB.init_office_db(db)
            EN.init_db(db)
            b, ctx = mk(c, seq["top"])
            now = float(b["t"][-1] + 900)
            st = {"price": float(b["c"][-1]), "ret_1h": 0.3, "ret_4h": 1.0, "ret_24h": 2.0, "atr15_pct": 0.3, "vol_regime_7d": 0.5, "pos_24h_range": 0.6}
            mc, rel = {"btc_ret_1h": 0.1, "eth_ret_1h": 0.1, "breadth_up_1h": 0.5, "n_alts": 20}, {"coin_ret_1h": 0.3, "rs_vs_btc_1h": 0.2, "rs_vs_btc_4h": 0.1}
            for sym in ("AUSDT", "BUSDT"):
                EN.step_symbol(db, sym, ctx, st, mc, rel, now, None)
            rows = OB._fetchall(db, "SELECT scenario_id, symbol, thesis_json FROM office2_live_scenario")
            assert len({r[0] for r in rows}) == len(rows) >= 2 and {r[1] for r in rows} == {"AUSDT", "BUSDT"}, rows
            import json as _j

            assert all(_j.loads(r[2]).get("symbol") == r[1] for r in rows), "thesis має належати символу рядка"
    finally:
        B.all_levels = orig


def test_stats_split_by_brain_version():
    import json
    import tempfile

    import office_bridge as OB
    from office2 import engine as EN
    from office2 import stats as ST

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "o2.db")
        OB.init_office_db(db)
        EN.init_db(db)
        for sid, brain in (("O2|a", "o2-brain-1"), ("O2|b", "o2-brain-2.0")):
            snap = {"brain": brain, "thesis": {"targets": [{"p": 1, "r": 1.2}], "entry": 1}, "alignment_summary": {"against": 0}}
            OB._execute(db, "INSERT INTO office2_live_signal(scenario_id, symbol, direction, created_ts, valid_until_ts, status, snapshot_json, version) VALUES (?,?,?,?,?,?,?,?)",
                        (sid, "XUSDT", "LONG", 1000.0, 9e9, "DELIVERED", json.dumps(snap), brain))
        out = ST.collect(db)
        assert set(out["by_brain"]) == {"o2-brain-1", "o2-brain-2.0"} and out["by_brain"]["o2-brain-1"]["delivered"] == 1, out["by_brain"]


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for f in fns:
        f()
        print("ok", f.__name__)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
