"""A7 pure shadow regression tests, no live imports."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.br_profitability_shadow import evaluate_shadow


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.plan = {"created_ts": 1790000000, "entry": 100, "sl": 99.6, "direction": "LONG"}

    def test_unknown_never_false(self):
        result = evaluate_shadow(self.plan)
        self.assertIsNone(result["f_hour"])
        self.assertIsNone(result["f_min_stop"])
        self.assertIsNone(result["sl_htf_price"])

    def test_hypotheses(self):
        r = evaluate_shadow(self.plan, min_stop_pct=.5, allowed_utc_hours=set(range(24)),
                            previous_sl_ts=1790000000 - 3600, pause_seconds=7200,
                            previous_same_ts=1790000000 - 7201, dedup_seconds=7200)
        self.assertFalse(r["f_min_stop"])
        self.assertFalse(r["f_pause_sl"])
        self.assertTrue(r["f_dedup"])
        self.assertTrue(r["f_hour"])

    def test_htf_stop_only_beyond_existing(self):
        self.assertIsNone(evaluate_shadow(self.plan, htf_swing_price=99.8)["sl_htf_price"])
        self.assertEqual(evaluate_shadow(self.plan, htf_swing_price=99.4)["sl_htf_price"], 99.4)

    def test_pure_no_mutation(self):
        before = dict(self.plan)
        evaluate_shadow(self.plan)
        self.assertEqual(self.plan, before)


if __name__ == "__main__":
    unittest.main()
