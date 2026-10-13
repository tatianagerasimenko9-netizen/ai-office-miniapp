"""Regression tests for causal methodology features; no live services required."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import unittest

from office2.method_closed_bar_features import from_closed_bars
from office2.method_predicates import evaluate


def bar(op, high, low, close, volume):
    return {"open": op, "high": high, "low": low, "close": close, "volume": volume}


class ClosedBarFeaturesTest(unittest.TestCase):
    def setUp(self):
        self.bars = [
            bar(100, 104, 98, 102, 10),
            bar(102, 106, 100, 105, 20),
            bar(105, 113, 103, 112, 50),
        ]

    def test_cutoff_ignores_future_candle(self):
        before = from_closed_bars(self.bars, 2)
        future = bar(112, 200, 1, 199, 100000)
        self.assertEqual(before, from_closed_bars(self.bars + [future], 2))

    def test_computed_inputs_are_consumed(self):
        evidence = from_closed_bars(self.bars, 2)
        self.assertEqual(evidence["D-VOLUME-PRICE"]["average_volume"], 15)
        self.assertEqual(evidence["D-VOLUME-PRICE"]["current_volume"], 50)
        self.assertIn(evaluate("D-VOLUME-PRICE", evidence["D-VOLUME-PRICE"])["status"],
                      ("PASS", "FAIL"))

    def test_bad_bars_fail_closed(self):
        self.assertEqual(from_closed_bars(self.bars, 3), {})
        self.assertEqual(from_closed_bars(self.bars[:2] + [bar(10, 8, 9, 10, 5)], 2), {})
        self.assertEqual(from_closed_bars(self.bars, True), {})

    def test_no_fabricated_inputs_for_other_rules(self):
        evidence = from_closed_bars(self.bars, 2)
        self.assertNotIn("X-NOT-SPECIFIED-BULKOWSKI", evidence)
        self.assertNotIn("X-NOT-SPECIFIED-DARIA-LTF-ENTRY-TP", evidence)



class ExtendedCausalFeaturesTest(unittest.TestCase):
    def test_pivot_uses_closed_right_candle(self):
        from office2.method_closed_bar_features import from_closed_bars
        bars = [bar(10, 12, 9, 11, 10), bar(11, 17, 10, 16, 10),
                bar(14, 15, 11, 12, 10), bar(12, 50, 1, 30, 1000)]
        evidence = from_closed_bars(bars, 2)
        self.assertEqual(evidence["S-SWING3"]["center_high"], 17)
        self.assertEqual(evidence, from_closed_bars(bars[:3], 2))

    def test_daily_range_excludes_current_day(self):
        from office2.method_closed_bar_features import daily_atr_observation
        days = [{"high": 10 + i, "low": 5} for i in range(6)]
        evidence = daily_atr_observation(days, 5)
        self.assertEqual(evidence["G-ATR-CALC"]["previous_ranges"], [5, 6, 7, 8, 9])
        days[5] = {"high": 100000, "low": 0}
        self.assertEqual(evidence, daily_atr_observation(days, 5))

class NewCausalRulesTest(unittest.TestCase):
    def test_sweep_only_after_closed_candle(self):
        from office2.method_closed_bar_features import from_closed_bars
        bars = [bar(10, 12, 9, 11, 100) for _ in range(6)]
        bars.append(bar(10, 11, 8, 10, 100))
        evidence = from_closed_bars(bars, 6)
        for rule in ("G-FB-1BAR", "S-LIQUIDITY-RAID",
                     "D-FALSE-BREAK", "G-FALSE-BREAK-DEF"):
            self.assertIn(rule, evidence)
        self.assertEqual(evidence, from_closed_bars(
            bars + [bar(20, 100, 1, 80, 10000)], 6))

    def test_two_bar_rejection(self):
        from office2.method_closed_bar_features import from_closed_bars
        bars = [bar(10, 12, 9, 11, 100) for _ in range(6)]
        bars += [bar(11, 14, 10, 13, 100), bar(13, 14, 10, 11, 100)]
        evidence = from_closed_bars(bars, 7)
        self.assertTrue(evidence["G-FB-2BAR"]["second_rejected"])


class CandlePatternTest(unittest.TestCase):
    def test_engulfing_requires_closed_opposite_body(self):
        from office2.method_closed_bar_features import from_closed_bars
        bars = [bar(10, 12, 8, 11, 10),
                bar(11, 12, 9, 10, 10),
                bar(9, 13, 8, 12, 10)]
        evidence = from_closed_bars(bars, 2)
        self.assertEqual(evidence["O-CANDLE-PATTERNS"]["pattern_name"], "ENGULFING")
        self.assertEqual(evidence, from_closed_bars(
            bars + [bar(20, 40, 1, 30, 100)], 2))


class RangeDurationTest(unittest.TestCase):
    def test_range_duration_uses_prior_reference(self):
        from office2.method_closed_bar_features import from_closed_bars
        candles = [bar(10, 12, 9, 11, 10) for _ in range(9)]
        result = from_closed_bars(candles, 8)
        self.assertEqual(result["G-LVL-CONSOLIDATION"]["bars_held"], 3)
        self.assertEqual(result["G-FB-COMPLEX"]["inside_bars"], 3)
        self.assertEqual(result, from_closed_bars(
            candles + [bar(20, 50, 1, 40, 100)], 8))

if __name__ == "__main__":
    unittest.main()
