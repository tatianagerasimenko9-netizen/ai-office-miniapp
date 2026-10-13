"""Validate source methodology processing order."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from office2.method_evidence import load_rules
from office2.method_sequence import PHASES, validate_sequence, decision_trace


class MethodSequenceTests(unittest.TestCase):
    def test_complete_registry(self):
        rules = load_rules()
        self.assertEqual(len(rules), 82)
        self.assertTrue(validate_sequence(rules))
        self.assertEqual(sum(len(p["rules"]) for p in decision_trace(rules)), 82)

    def test_dependency_order(self):
        names = [name for name, _ in PHASES]
        self.assertLess(names.index("03_LEVELS_LIQUIDITY"), names.index("05_SCENARIO"))
        self.assertLess(names.index("05_SCENARIO"), names.index("06_ENTRY"))
        self.assertLess(names.index("06_ENTRY"), names.index("07_RISK"))

    def test_missing_rule_fails(self):
        with self.assertRaises(ValueError):
            validate_sequence(load_rules()[:-1])


if __name__ == "__main__":
    unittest.main()
