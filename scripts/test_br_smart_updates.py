import unittest
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
if __name__ == "__main__":
    unittest.main()
