"""B2: deterministic causality and stop-priority tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.htf_stop_replay import confirmed_swings, structural_stop, follow, stop_hunt


class HtfTests(unittest.TestCase):
    def test_future_confirming_bar_unavailable(self):
        b = [{"t":i*3600, "h":110 if i==2 else 105, "l":90 if i==2 else 95, "o":100, "c":100} for i in range(5)]
        self.assertEqual(confirmed_swings(b,4*3600,3600,k=2), [])
        self.assertEqual(len(confirmed_swings(b,5*3600,3600,k=2)),1)

    def test_confirmed_lower_stop(self):
        b = [{"t":i*3600, "h":104, "l":90 if i==2 else 97, "o":100, "c":100} for i in range(5)]
        self.assertEqual(structural_stop(b,5*3600,3600,"L",95),90)
        self.assertIsNone(structural_stop(b,4*3600,3600,"L",95))

    def test_same_candle_stop_first(self):
        bars=[{"t":100, "o":100,"h":103,"l":98,"c":100}]
        result=follow(bars,100,"L",100,99,102)
        self.assertEqual(result["stop_at"],100)
        self.assertIsNone(result["target_at"])

    def test_stop_hunt_is_post_stop_only(self):
        b=[{"t":100,"h":103,"l":98},{"t":160,"h":103,"l":100}]
        self.assertTrue(stop_hunt(b,100,"L",102,3600))
        self.assertFalse(stop_hunt(b,160,"L",102,3600))


if __name__=="__main__":
    unittest.main()
