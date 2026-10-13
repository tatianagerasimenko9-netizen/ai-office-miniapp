"""Source-method integration tests; no network, no live orders."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from office2.method_evidence import advisory_snapshot, load_rules, rule_coverage


class MethodEvidenceTests(unittest.TestCase):
    def test_registry_is_nonempty_and_unique(self):
        rules = load_rules()
        self.assertGreaterEqual(len(rules), 82)
        self.assertEqual(len(rules), len({r["rule_id"] for r in rules}))
        coverage = rule_coverage(rules)
        self.assertEqual(coverage["total"], len(rules))

    def test_unknown_is_not_pass_or_gate(self):
        rules = load_rules()
        snap = advisory_snapshot(rules, symbol="APEUSDT", asof_utc="2026-10-13T00:00:00Z")
        self.assertEqual(snap["decision"], "NOT_EVALUATED")
        self.assertEqual(len(snap["rule_evaluations"]), len(rules))
        self.assertTrue(all(r["status"] == "UNKNOWN" and r["decision_role"] == "SHADOW" for r in snap["rule_evaluations"]))
        self.assertEqual(list(snap["timeframes"]), ["D1", "H4", "H1", "M15", "M5", "M1"])

    def test_evidence_does_not_change_role(self):
        rules = load_rules()
        rid = rules[0]["rule_id"]
        snap = advisory_snapshot(rules, symbol="BTCUSDT", asof_utc="2026-10-13T00:00:00Z",
                                 evidence_by_rule={rid: {"status": "PASS", "evidence": ["closed candle"]}})
        self.assertEqual(snap["rule_evaluations"][0]["status"], "PASS")
        self.assertEqual(snap["rule_evaluations"][0]["decision_role"], "SHADOW")
        with self.assertRaises(ValueError):
            advisory_snapshot(rules, symbol="BTCUSDT", asof_utc="now",
                              evidence_by_rule={"FAKE-RULE": {"status": "PASS"}})

    def test_duplicates_rejected(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "rules.jsonl"
            rule = {"rule_id": "D-1", "method": "DARIA", "source_files": []}
            path.write_text(json.dumps(rule) + "\n" + json.dumps(rule) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_rules(path)


if __name__ == "__main__":
    unittest.main()
