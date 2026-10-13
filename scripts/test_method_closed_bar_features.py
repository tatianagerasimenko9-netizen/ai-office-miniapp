"""Regression tests for causal methodology features; no live services required."""
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


if __name__ == "__main__":
    unittest.main()
