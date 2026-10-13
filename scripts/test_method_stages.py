"""Top-down source-method stage coverage tests."""
import unittest

from office2.method_evidence import load_rules
from office2.method_stages import STAGES, staged_registry, stage_for


class MethodStageTests(unittest.TestCase):
    def test_every_rule_in_exactly_one_stage(self):
        rules = load_rules()
        stages = staged_registry(rules)
        self.assertEqual(tuple(stages), STAGES)
        ids = [rule["rule_id"] for items in stages.values() for rule in items]
        self.assertEqual(len(ids), len(rules))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {rule["rule_id"] for rule in rules})

    def test_unimplemented_rules_do_not_automatically_pass(self):
        stages = staged_registry(load_rules())
        self.assertTrue(all(item["status"] == "UNKNOWN" for items in stages.values() for item in items))

    def test_stage_roles(self):
        self.assertEqual(stage_for({"rule_id": "G-LVL-FLOATING", "method": "GERCHIK_LEVELS"}), "D1_H4_CONTEXT")
        self.assertEqual(stage_for({"rule_id": "G-RR-MIN3", "method": "GERCHIK_RISK"}), "RISK_EXECUTION")
        self.assertEqual(stage_for({"rule_id": "X-QA-RUNE", "method": "OFFICE_PRODUCT_QA"}), "QA_RESEARCH")


if __name__ == "__main__":
    unittest.main()
