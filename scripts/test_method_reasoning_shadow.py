"""Regression tests for Office methodology observations and phase reasoning."""
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from office2.method_predicates import evaluate
from office2.method_sequence import PHASES, evaluate_chain


class MethodologyShadowTests(unittest.TestCase):
    def test_no_missing_data_can_pass(self):
        for _, ids in PHASES:
            for rule_id in ids:
                self.assertNotEqual(evaluate(rule_id, {})["status"], "PASS", rule_id)

    def test_volume_price_measurement(self):
        result = evaluate("D-VOLUME-PRICE", {
            "current_volume": 200, "average_volume": 100, "price_change": -1
        })
        self.assertEqual(result["volume_ratio"], 2)
        self.assertEqual(result["price_direction"], "DOWN")

    def test_pressure_requires_all_flags(self):
        self.assertEqual(evaluate("G-PRESS", {
            "higher_lows": True, "level_tested": True,
            "pullbacks_shrinking": False
        })["status"], "FAIL")

    def test_phase_reasoning_preserves_unknown(self):
        rules = [{"rule_id": rid} for _, ids in PHASES for rid in ids]
        trace = evaluate_chain(rules)
        self.assertEqual(trace["evaluated"], 82)
        self.assertEqual(trace["counts"]["UNKNOWN"], 82)
        self.assertEqual(trace["decision"], "UNDETERMINED")
        self.assertEqual(len(trace["reasoning"]), len(PHASES))
        self.assertTrue(all(not phase["complete"] for phase in trace["reasoning"]))


if __name__ == "__main__":
    unittest.main()
