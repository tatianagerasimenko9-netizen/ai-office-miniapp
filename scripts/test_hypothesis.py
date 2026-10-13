"""Hypothesis engine: families, scenarios A/B/C, no-lookahead, observation transitions, no READY/Telegram side effects."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import numpy as np

from test_method_inputs import make_ctx, H, D
from office2 import hypothesis as HY
from office2.method_inputs import build_inputs

import office_bridge as OB


def ctx_with_sweep(n=200):
    """Flat range around 100 then a bar that sweeps the low and closes back inside."""
    ctx = make_ctx(n15=n)
    m = ctx["m15"]
    base = 100.0
    m["o"][:] = base; m["c"][:] = base; m["h"][:] = base + 1; m["l"][:] = base - 1; m["v"][:] = 10
    k = n - 1
    m["o"][k], m["l"][k], m["h"][k], m["c"][k] = base, base - 2.0, base + 0.4, base + 0.2   # low below 99, close above
    return ctx, float(m["t"][k]) + H


class HypothesisTest(unittest.TestCase):
    def test_false_break_hypothesis_is_explained(self):
        ctx, now = ctx_with_sweep()
        inp = build_inputs(ctx, now, None)
        hs = HY.build("XUSDT", ctx, now, inp)
        fb = [h for h in hs if h["family"] == "FALSE_BREAK_RECLAIM"]
        self.assertEqual(len(fb), 1)
        h = fb[0]
        self.assertEqual(h["direction"], "LONG")
        self.assertTrue(h["supports"] and h["missing"] and h["next_checks"])
        self.assertEqual(set(h["scenarios"]), {"A", "B", "C"})
        for s in h["scenarios"].values():
            self.assertTrue(s["conditions"] and s["next_action"] and s["review"])
        self.assertIsNone(h["plan"])
        self.assertFalse(h["is_ready"])
        self.assertEqual(h["role"], "SHADOW")
        self.assertLess(h["invalidation"], h["level"])

    def test_no_hypothesis_without_pattern(self):
        ctx = make_ctx()
        now = float(ctx["m15"]["t"][-1]) + H
        hs = HY.build("XUSDT", ctx, now, build_inputs(ctx, now, None))
        for h in hs:    # whatever is found must be a known family with an explanation
            self.assertIn(h["family"], ("FALSE_BREAK_RECLAIM", "BREAKOUT_RETEST", "POST_IMPULSE_BASE"))
            self.assertTrue(h["supports"])

    def test_future_bars_do_not_change_hypotheses(self):
        ctx, now = ctx_with_sweep()
        a = HY.build("XUSDT", ctx, now, build_inputs(ctx, now, None))
        ctx2, _ = ctx_with_sweep()
        ctx2["m15"]["h"] = np.r_[ctx2["m15"]["h"], [500.0] * 5]
        ctx2["m15"]["l"] = np.r_[ctx2["m15"]["l"], [1.0] * 5]
        for k in ("t",):
            ctx2["m15"][k] = np.r_[ctx2["m15"][k], ctx2["m15"][k][-1] + H * np.arange(1, 6)]
        for k in ("o", "c", "v"):
            ctx2["m15"][k] = np.r_[ctx2["m15"][k], [250.0] * 5]
        b = HY.build("XUSDT", ctx2, now, build_inputs(ctx2, now, None))
        self.assertEqual([h["id"] for h in a], [h["id"] for h in b])
        self.assertEqual([h["level"] for h in a], [h["level"] for h in b])

    def test_plan_attached_only_from_real_ready_same_direction(self):
        ctx, now = ctx_with_sweep()
        inp = build_inputs(ctx, now, None)
        th = {"state": "READY", "dir": "LONG", "entry": 100.2, "sl": 98.9, "targets": [{"p": 103.0}]}
        h = [x for x in HY.build("XUSDT", ctx, now, inp, plan_th=th) if x["family"] == "FALSE_BREAK_RECLAIM"][0]
        self.assertEqual(h["plan"]["rr_tp1"], round(2.8 / 1.3, 2))
        th["dir"] = "SHORT"
        h = [x for x in HY.build("XUSDT", ctx, now, inp, plan_th=th) if x["family"] == "FALSE_BREAK_RECLAIM"][0]
        self.assertIsNone(h["plan"])

    def test_smc_model_becomes_hypothesis_with_missing_step(self):
        ctx, now = ctx_with_sweep()
        smc = {"price": 100.2, "models": {"LONG": {"REVERSAL": {
            "state": "WAIT", "stage": 2, "reason": "WAIT · RAID є, чекаємо зсув структури (MS)", "need": {"text": "MS: закриття M15 вище 100.5"},
            "sweep": {"level": {"p": 99.0}, "extreme": 98.0}, "steps": [{"step": "RAID", "ok": True, "detail": "рівень 99"}, {"step": "MS", "ok": False}],
            "evidence_against": []}}}}
        hs = [h for h in HY.build("XUSDT", ctx, now, {}, smc_res=smc) if h["family"] == "SMC_REVERSAL"]
        self.assertEqual(len(hs), 1)
        self.assertIn("MS: закриття M15 вище 100.5", hs[0]["missing"])
        self.assertTrue(any("не виконано: MS" in c for c in hs[0]["contradicts"]))

    def test_observation_lifecycle_confirmed_refuted_expired_and_dedup(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "o.db")
            OB.init_office_db(db)
            ctx, now = ctx_with_sweep()
            h = [x for x in HY.build("XUSDT", ctx, now, build_inputs(ctx, now, None)) if x["family"] == "FALSE_BREAK_RECLAIM"][0]
            HY.observe(db, "XUSDT", [h], ctx["m15"], now)
            HY.observe(db, "XUSDT", [h], ctx["m15"], now + 900)       # same structure -> same row, no duplicate
            self.assertEqual(len(HY.list_hypotheses(db)), 1)
            m = ctx["m15"]
            n = len(m["t"])

            def extend(bars):
                out = {k: np.array(v, dtype=float) for k, v in m.items()}
                for i, (o, hh, ll, c) in enumerate(bars, 1):
                    out["t"] = np.r_[out["t"], m["t"][-1] + H * i]
                    for k, v in zip(("o", "h", "l", "c", "v"), (o, hh, ll, c, 10.0)):
                        out[k] = np.r_[out[k], v]
                return out
            risk = h["risk_ref"]
            # confirmed: price rises 1R from ref before closing below invalidation
            up = extend([(100.2, 100.2 + 1.2 * risk, 100.1, 100.2 + 1.1 * risk)])
            t_now = float(up["t"][-1]) + H
            tr = HY.progress(db, "XUSDT", up, t_now)
            self.assertEqual(tr[0]["state"], "CONFIRMED")
            self.assertEqual(HY.list_hypotheses(db), [])
            # terminal state is never revived by a new cycle with the same id
            HY.observe(db, "XUSDT", [h], up, t_now)
            self.assertEqual(HY.list_hypotheses(db), [])
            self.assertEqual(len(HY.list_hypotheses(db, "CONFIRMED")), 1)
            # refuted on a second DB
            db2 = os.path.join(td, "o2.db")
            OB.init_office_db(db2)
            HY.observe(db2, "XUSDT", [h], m, now)
            dn = extend([(100.0, 100.1, 97.0, 97.5)])
            tr = HY.progress(db2, "XUSDT", dn, float(dn["t"][-1]) + H)
            self.assertEqual(tr[0]["state"], "REFUTED")
            # expired
            db3 = os.path.join(td, "o3.db")
            OB.init_office_db(db3)
            HY.observe(db3, "XUSDT", [h], m, now)
            drift = extend([(100.2, 100.3, 100.1, 100.2)] * HY.TTL_BARS["FALSE_BREAK_RECLAIM"])
            tr = HY.progress(db3, "XUSDT", drift, float(drift["t"][-1]) + H)
            self.assertEqual(tr[0]["state"], "EXPIRED")

    def test_progress_ignores_bars_not_yet_closed(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "o.db")
            OB.init_office_db(db)
            ctx, now = ctx_with_sweep()
            h = [x for x in HY.build("XUSDT", ctx, now, build_inputs(ctx, now, None)) if x["family"] == "FALSE_BREAK_RECLAIM"][0]
            HY.observe(db, "XUSDT", [h], ctx["m15"], now)
            m = {k: np.r_[v, v[-1]] for k, v in ctx["m15"].items()}
            m["t"][-1] = ctx["m15"]["t"][-1] + H
            m["c"][-1], m["l"][-1] = 90.0, 85.0                                  # a crash in a bar that is still forming
            tr = HY.progress(db, "XUSDT", m, float(m["t"][-1]) + 10)             # now is inside the new bar
            self.assertEqual(tr, [])

    def test_module_has_no_side_effect_imports(self):
        with open(os.path.join(os.path.dirname(HY.__file__), "hypothesis.py"), encoding="utf-8") as fh:
            src = fh.read()
        for bad in ("telegram", "office_telegram", "emit_ready", "send_message", "binance.com/fapi/v1/order"):
            self.assertNotIn(bad, src)


class ReplayCoreTest(unittest.TestCase):
    def test_replay_core_is_causal_and_has_control(self):
        import replay_hypotheses as R
        rng = np.random.default_rng(5)

        def mk(n, w, t0, vol):
            t = t0 + np.arange(n) * w
            c = 100 + np.cumsum(rng.normal(0, vol, n))
            o = np.r_[c[0], c[:-1]]
            h = np.maximum(o, c) + abs(rng.normal(0, vol / 3, n))
            l = np.minimum(o, c) - abs(rng.normal(0, vol / 3, n))
            v = rng.random(n) * 100
            return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "tbv": v * 0.5}
        t0 = 1_750_000_000.0 // 900 * 900
        arrs = {"m15": mk(3000, 900, t0, 0.3), "h4": mk(600, 14400, t0 - 20 * 86400, 1.0), "d1": mk(200, 86400, t0 - 100 * 86400, 2.0), "w1": mk(50, 604800, t0 - 300 * 86400, 3)}
        rows = R.core("TEST", arrs, t0 + 20 * 86400, t0 + 30 * 86400)
        hyp = [r for r in rows if "id" in r]
        self.assertTrue(hyp)
        for r in hyp:
            self.assertIn(r["state"], ("CONFIRMED", "REFUTED", "EXPIRED", "ACTIVE"))
            self.assertIn(r["ctl_state"], ("CONFIRMED", "REFUTED", "EXPIRED", "ACTIVE"))
        # poisoning bars far after the window must not change which hypotheses exist at decision time
        arrs2 = {k: {kk: np.array(vv, dtype=float) for kk, vv in v.items()} for k, v in arrs.items()}
        arrs2["m15"]["h"][-100:] += 50.0
        arrs2["m15"]["l"][-100:] -= 50.0
        rows2 = R.core("TEST", arrs2, t0 + 20 * 86400, t0 + 30 * 86400)
        self.assertEqual([r["id"] for r in hyp], [r["id"] for r in rows2 if "id" in r])


if __name__ == "__main__":
    unittest.main()
