import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from office_br.idea_matcher import same_idea

BASE = dict(symbol="ETHUSDT", direction="SHORT", status="SENT", entry=2350., sl=2360., level=2355., created_ts=1000.)

class SmartUpdatesTests(unittest.TestCase):
    def test_duplicate(self):
        self.assertTrue(same_idea(BASE,"ETHUSDT",dict(direction="SHORT",entry=2351.,sl=2361.,level=2354.),1100.))
    def test_independent_price(self):
        self.assertFalse(same_idea(BASE,"ETHUSDT",dict(direction="SHORT",entry=2370.,sl=2380.,level=2375.),1100.))
    def test_terminal(self):
        self.assertFalse(same_idea({**BASE,"status":"SL"},"ETHUSDT",dict(direction="SHORT",entry=2350.,sl=2360.,level=2355.),1100.))
    def test_opposite(self):
        self.assertFalse(same_idea(BASE,"ETHUSDT",dict(direction="LONG",entry=2350.,sl=2360.,level=2355.),1100.))
    def test_old(self):
        self.assertFalse(same_idea(BASE,"ETHUSDT",dict(direction="SHORT",entry=2350.,sl=2360.,level=2355.),1000.+25*3600))

    def test_production_same_break_alternate_levels(self):
        # Read-only fixtures from 24 Oct production: 634/635, 638/639, 641/642, 649/650.
        # Both READYs had the same symbol, direction, break, entry and SL;
        # their detector levels differed enough to evade the prior 0.35R rule.
        fixtures = (
            ("SEIUSDT", 1792826100, .05516, .055325, .05525, .05532),
            ("ONDOUSDT", 1792826100, .4082, .41147285714285714, .4116, .4113),
            ("NEARUSDT", 1792827900, 4.567, 4.586821428571429, 4.583, 4.59),
            ("SOLUSDT", 1792832400, 101.38, 101.70964285714287, 101.63, 101.7),
        )
        for symbol, break_ts, entry, sl, first_level, second_level in fixtures:
            with self.subTest(symbol=symbol):
                old = dict(symbol=symbol, direction="SHORT", status="SENT",
                           entry=entry, sl=sl, level=first_level,
                           break_ts=break_ts, created_ts=1000.)
                new = dict(direction="SHORT", entry=entry, sl=sl,
                           level=second_level, break_ts=break_ts)
                self.assertTrue(same_idea(old, symbol, new, 1000.))

    def test_same_break_but_different_execution_not_forced_duplicate(self):
        old = dict(**BASE, break_ts=900.)
        new = dict(direction="SHORT", break_ts=900., entry=2360., sl=2370., level=2365.)
        self.assertFalse(same_idea(old, "ETHUSDT", new, 1100.))

    def test_same_execution_different_break_and_far_level_independent(self):
        old = dict(**BASE, break_ts=900.)
        new = dict(direction="SHORT", break_ts=1800., entry=2350., sl=2360., level=2370.)
        self.assertFalse(same_idea(old, "ETHUSDT", new, 1100.))

if __name__ == "__main__":
    unittest.main()
