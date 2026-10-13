"""Offline positive, negative and missing-data checks for source predicates."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest

from office2.method_predicates import evaluate


class MethodPredicateTests(unittest.TestCase):
    def test_close_direction(self):
        self.assertEqual(evaluate("G-SIGNAL-CLOSE", {"close": 101, "level": 100, "direction": "LONG"})["status"], "PASS")
        self.assertEqual(evaluate("G-SIGNAL-CLOSE", {"close": 101, "level": 100, "direction": "SHORT"})["status"], "FAIL")
        self.assertEqual(evaluate("G-SIGNAL-CLOSE", {"close": 100, "level": 100, "direction": "LONG"})["status"], "FAIL")

    def test_paranormal_bar(self):
        self.assertEqual(evaluate("G-LVL-PARANORMAL", {"range": 20, "average_range": 10})["status"], "PASS")
        self.assertEqual(evaluate("G-LVL-PARANORMAL", {"range": 19, "average_range": 10})["status"], "FAIL")

    def test_reward_risk(self):
        self.assertEqual(evaluate("G-RR-MIN3", {"reward": 3, "risk": 1})["status"], "PASS")
        self.assertEqual(evaluate("G-RR-MIN3", {"reward": 2, "risk": 1})["status"], "FAIL")

    def test_unknown_never_passes(self):
        self.assertEqual(evaluate("G-RR-MIN3", {"reward": 3})["status"], "UNKNOWN")
        self.assertEqual(evaluate("G-LVL-PARANORMAL", {"range": 20, "average_range": 0})["status"], "UNKNOWN")
        self.assertEqual(evaluate("X-NOT-SPECIFIED-DARIA-LTF-ENTRY-TP", {})["status"], "UNKNOWN")

    def test_atr_measurement(self):
        self.assertEqual(evaluate("G-ATR-DAYUSED", {"day_range": 15, "daily_atr": 10})["ratio"], 1.5)


if __name__ == "__main__":
    unittest.main()
