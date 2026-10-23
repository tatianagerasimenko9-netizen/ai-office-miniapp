import os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.scheduler import Scheduler
from office_br.universe import rotate
def market():
    syms=["BTCUSDT","XAUUSDT","CLUSDT","BZUSDT","NATGASUSDT"] + [f"TEST{i}USDT" for i in range(150)]
    return {"symbols":[{"symbol":s,"status":"TRADING","contractType":"PERPETUAL","quoteAsset":"USDT","marginAsset":"USDT"} for s in syms]}
class Tests(unittest.TestCase):
    def test_all_150_rotate_without_full_rest_fanout(self):
        os.environ["BR_LIVE_DYNAMIC_BATCH"]="12"
        try:
            s=Scheduler(); batches=[s.batch(market,now=1000+i*60) for i in range(30)]
            visited={x for b in batches for x in b}
            self.assertGreaterEqual(len(visited),150)
            self.assertTrue({"XAUUSDT","CLUSDT","BZUSDT","NATGASUSDT"}.issubset(visited))
            self.assertTrue(all(len(b)<=12 for b in batches))
        finally: os.environ.pop("BR_LIVE_DYNAMIC_BATCH",None)
    def test_ban_means_no_binance_access(self):
        s=Scheduler()
        self.assertEqual(s.batch(lambda: self.fail("must not fetch"), hard_backoff=123),())
    def test_bad_universe_fails_closed(self):
        self.assertEqual(Scheduler().batch(lambda: {"symbols":[]}),())
if __name__=="__main__": unittest.main()
