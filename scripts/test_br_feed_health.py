import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.feed_health import FeedHealth

class FeedHealthTests(unittest.TestCase):
    def test_normal_silence_is_not_outage(self):
        h=FeedHealth()
        self.assertIsNone(h.observe(12,12))
        self.assertIsNone(h.observe(12,12))
    def test_one_outage_and_one_recovery(self):
        h=FeedHealth(3)
        self.assertIsNone(h.observe(0,12))
        self.assertIsNone(h.observe(0,12))
        self.assertEqual(h.observe(0,12),"OUTAGE")
        self.assertIsNone(h.observe(0,12))
        self.assertIsNone(h.observe(5,12))
        self.assertEqual(h.observe(12,12),"RECOVERED")
        self.assertIsNone(h.observe(12,12))
    def test_bad_telemetry_is_not_success(self):
        h=FeedHealth(1)
        self.assertIsNone(h.observe(0,0))
        self.assertIsNone(h.observe(13,12))
        self.assertEqual(h.observe(0,12),"OUTAGE")
if __name__=="__main__":
    unittest.main()
