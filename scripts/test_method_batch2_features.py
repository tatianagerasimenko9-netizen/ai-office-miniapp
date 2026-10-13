"""Batch 2 closed-bar features (+7 rules): no-lookahead, negative cases, evaluate_chain."""
import unittest

from office2.method_closed_bar_features import from_closed_bars
from office2.method_predicates import evaluate
from office2.method_sequence import evaluate_chain

NEW = ("G-SIGNAL-CLOSE", "S-OTE-PD", "G-LVL-FLOATING", "G-LVL-TRENDBREAK",
       "G-ATR-DAYUSED", "G-FB-DEPTH")


def bar(o, h, l, c, v=100):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def flat(n=6):
    return [bar(10, 12, 9, 11) for _ in range(n)]


class Batch2Test(unittest.TestCase):
    def sweep_long(self):
        return flat() + [bar(10, 11, 8, 10)]  # low 8 < floor 9 < close 10

    def test_sweep_rules_and_daily_rules(self):
        bars = self.sweep_long()
        ev = from_closed_bars(bars, 6, daily_ranges=[4, 4, 4], day_bars=bars[-3:])
        for rule in NEW:
            self.assertIn(rule, ev, rule)
        self.assertEqual(ev["G-SIGNAL-CLOSE"], {"close": 10, "level": 9, "direction": "LONG"})
        self.assertEqual(evaluate("G-SIGNAL-CLOSE", ev["G-SIGNAL-CLOSE"])["status"], "PASS")
        self.assertEqual(ev["G-FB-DEPTH"]["break_depth"], 1)
        self.assertEqual(evaluate("G-FB-DEPTH", ev["G-FB-DEPTH"])["status"], "PASS")  # 1 <= 0.3*4
        self.assertEqual(evaluate("G-ATR-DAYUSED", ev["G-ATR-DAYUSED"])["status"], "PASS")
        self.assertEqual(evaluate("S-OTE-PD", ev["S-OTE-PD"])["status"], "PASS")  # 10 in lower half

    def test_no_lookahead(self):
        bars = self.sweep_long()
        a = from_closed_bars(bars, 6, daily_ranges=[4, 4, 4], day_bars=bars[-3:])
        b = from_closed_bars(bars + [bar(50, 500, 1, 400, 9)], 6, daily_ranges=[4, 4, 4], day_bars=bars[-3:])
        self.assertEqual(a, b)

    def test_missing_daily_context_is_absent_not_invented(self):
        ev = from_closed_bars(self.sweep_long(), 6)
        self.assertNotIn("G-ATR-DAYUSED", ev)
        self.assertNotIn("G-FB-DEPTH", ev)
        ev = from_closed_bars(self.sweep_long(), 6, daily_ranges=[4, 4], day_bars=[])
        self.assertNotIn("G-ATR-DAYUSED", ev)
        ev = from_closed_bars(self.sweep_long(), 6, daily_ranges=[4, 4, True], day_bars=None)
        self.assertNotIn("G-FB-DEPTH", ev)

    def test_negative_no_sweep(self):
        ev = from_closed_bars(flat(7), 6, daily_ranges=[4, 4, 4])
        for rule in ("G-SIGNAL-CLOSE", "S-OTE-PD", "G-FB-DEPTH"):
            self.assertNotIn(rule, ev)

    def test_floating_level_can_be_false(self):
        bars = [bar(10, 17 - i, 9, 11) for i in range(6)] + [bar(11, 12, 10.5, 11.5)]
        ev = from_closed_bars(bars, 6)
        self.assertEqual(ev["G-LVL-FLOATING"], {"fixed_level": False})
        self.assertEqual(evaluate("G-LVL-FLOATING", ev["G-LVL-FLOATING"])["status"], "FAIL")

    def test_trendbreak_positive_and_negative(self):
        up = [bar(10 + i, 12 + i, 9 + i, 11 + i) for i in range(6)]
        brk = up + [bar(17, 17.5, 12, 13)]  # bearish close below last higher-low (14)
        self.assertEqual(from_closed_bars(brk, 6)["G-LVL-TRENDBREAK"],
                         {"trend_reversed": True, "reversal_bar_confirmed": True})
        cont = up + [bar(16, 19, 15, 18)]
        self.assertEqual(from_closed_bars(cont, 6)["G-LVL-TRENDBREAK"],
                         {"trend_reversed": False, "reversal_bar_confirmed": False})

    def test_deep_false_break_fails(self):
        bars = flat() + [bar(10, 11, 5, 10.5)]
        ev = from_closed_bars(bars, 6, daily_ranges=[4, 4, 4])
        self.assertEqual(evaluate("G-FB-DEPTH", ev["G-FB-DEPTH"])["status"], "FAIL")

    def test_evaluate_chain_compatible(self):
        from office2.method_evidence import load_rules
        bars = self.sweep_long()
        ev = from_closed_bars(bars, 6, daily_ranges=[4, 4, 4], day_bars=bars[-3:])
        out = evaluate_chain(load_rules(), {r: ev[r] for r in NEW})
        states = {x["rule_id"]: x["status"] for ph in out["phases"] for x in ph["rules"]}
        for r in NEW:
            self.assertEqual(states[r], evaluate(r, ev[r])["status"], r)


if __name__ == "__main__":
    unittest.main()
