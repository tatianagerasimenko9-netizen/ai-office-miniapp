"""Offline tests for read-only LONG/SHORT candidate comparison."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from office2.method_direction_shadow import compare_candidates


class DirectionShadowTests(unittest.TestCase):
    def test_long_ready_beats_short_wait(self):
        result = compare_candidates({"state": "READY"}, {"state": "WAIT"})
        self.assertEqual(result["selected"], "LONG")
        self.assertEqual(result["role"], "SHADOW")

    def test_short_ready_beats_long_watch(self):
        self.assertEqual(compare_candidates({"state": "WATCH"}, {"state": "READY"})["selected"], "SHORT")

    def test_equal_candidates_do_not_force_direction(self):
        self.assertEqual(compare_candidates({"state": "READY"}, {"state": "READY"})["selected"], "CONFLICT")

    def test_missing_candidates(self):
        self.assertEqual(compare_candidates(None, None)["selected"], "NO_TRADE")


if __name__ == "__main__":
    unittest.main()
