"""Shared methodology input builder: closed-bar cut, no lookahead, live/replay parity."""
import unittest

import numpy as np

from office2.method_evidence import load_rules
from office2.method_inputs import build_inputs
from office2.method_sequence import evaluate_chain

H = 900.0
D = 86400.0


def make_ctx(n15=400, nd=40, jitter=0.0):
    rng = np.random.default_rng(3)
    t15 = 1_760_000_000.0 // H * H + np.arange(n15) * H
    c = 100 + np.cumsum(rng.normal(0, 0.3, n15))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + abs(rng.normal(0, 0.1, n15)) + 0.05
    l = np.minimum(o, c) - abs(rng.normal(0, 0.1, n15)) - 0.05
    v = rng.random(n15) * 100 + 1
    td = 1_760_000_000.0 // D * D - nd * D + np.arange(nd) * D
    cd = 100 + np.cumsum(rng.normal(0, 1.0, nd))
    od = np.r_[cd[0], cd[:-1]]
    hd = np.maximum(od, cd) + 0.8
    ld = np.minimum(od, cd) - 0.8
    return {"m15": {"t": t15, "o": o, "h": h, "l": l, "c": c, "v": v},
            "d1": {"t": td, "o": od, "h": hd, "l": ld, "c": cd, "v": rng.random(nd)}}


class InputsTest(unittest.TestCase):
    def test_future_bars_are_cut(self):
        ctx = make_ctx()
        now = float(ctx["m15"]["t"][300]) + H            # bar 300 just closed
        a = build_inputs(ctx, now, None)
        ctx2 = make_ctx()
        ctx2["m15"]["h"][301:] += 1000.0                  # poison the future (and the forming bar)
        ctx2["m15"]["c"][301:] += 500.0
        ctx2["m15"]["h"][301:] = ctx2["m15"]["c"][301:] + 1.0
        b = build_inputs(ctx2, now, None)
        self.assertEqual({k: v for k, v in a.items()}, {k: v for k, v in b.items()})
        self.assertEqual(a["S-SWING3"]["right_high"], float(ctx["m15"]["h"][300]))

    def test_forming_bar_excluded(self):
        ctx = make_ctx()
        now = float(ctx["m15"]["t"][300]) + H - 1        # bar 300 still forming
        a = build_inputs(ctx, now, None)
        self.assertEqual(a["S-SWING3"]["right_high"], float(ctx["m15"]["h"][299]))

    def test_d1_forming_day_excluded_from_atr(self):
        ctx = make_ctx()
        now = float(ctx["d1"]["t"][-1]) + D - 1          # last D1 still forming
        a = build_inputs(ctx, now, None)
        rng = [float(ctx["d1"]["h"][i] - ctx["d1"]["l"][i]) for i in range(len(ctx["d1"]["t"]) - 6, len(ctx["d1"]["t"]) - 1)]
        self.assertEqual(a["G-ATR-CALC"]["previous_ranges"], rng)

    def test_chain_and_provenance(self):
        ctx = make_ctx()
        now = float(ctx["m15"]["t"][-1]) + H
        inputs = build_inputs(ctx, now, None, rules=load_rules(), news_state="OK")
        out = evaluate_chain(load_rules(), inputs)
        self.assertEqual(out["evaluated"], 82)
        self.assertEqual(out["counts"]["NOT_APPLICABLE"], 4)
        st = {x["rule_id"]: x for ph in out["phases"] for x in ph["rules"]}
        self.assertEqual(st["S-SWING3"]["provenance"]["basis"], "SOURCE")
        self.assertIn("D-SESSIONS-NEWS", st)
        self.assertNotIn("G-RR-MIN3", [k for k, v in st.items() if v["status"] != "UNKNOWN"])   # no thesis -> UNKNOWN, not invented

    def test_plan_rules_need_ready_thesis(self):
        ctx = make_ctx()
        now = float(ctx["m15"]["t"][-1]) + H
        th = {"state": "READY", "dir": "LONG", "entry": 100.0, "sl": 99.0, "trigger_level": 99.5, "invalidation": {"price": 99.2},
              "targets": [{"p": 103.0}], "sizing": {"risk_usd": 10.0}}
        inputs = build_inputs(ctx, now, th, equity_usd=1000.0, journal={"closed_trades": 3, "daily_loss_usd": 0.0})
        for r in ("G-RR-MIN3", "G-STOP-CRYPTO", "G-RISK-TRADE", "G-TRIAL-100", "G-STOP-ATR"):
            self.assertIn(r, inputs)


if __name__ == "__main__":
    unittest.main()
