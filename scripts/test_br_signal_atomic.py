import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_bridge as OB
from office_br.store import record_signal, rows

SIGNAL = {"direction":"SHORT","level":2355.0,"break_ts":1000.0,
          "retest_ts":1100.0,"confirm_ts":1200.0,"entry":2350.0,
          "sl":2360.0,"targets":[{"p":2340.0}]}

class AtomicSignalTests(unittest.TestCase):
    def test_exact_duplicate_does_not_generate_second_signal(self):
        with tempfile.TemporaryDirectory() as folder:
            db=os.path.join(folder,"br.sqlite")
            OB.init_office_db(db)
            first=record_signal(db,"ETHUSDT",SIGNAL,{},now=1201.)
            second=record_signal(db,"ETHUSDT",SIGNAL,{},now=1202.)
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.assertEqual(len(rows(db)),1)

if __name__ == "__main__":
    unittest.main()
