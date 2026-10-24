"""B&R image must reject missing or misaligned market evidence."""
import datetime, json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.live_image import render
class TestImage(unittest.TestCase):
    def setUp(self):
        self.t=1792854000.
        self.row={"seq":678,"symbol":"ONDOUSDT","direction":"SHORT","level":.4034,"entry":.3988,
                  "sl":.4042,"confirm_ts":self.t,"targets_json":json.dumps([{"p":p} for p in [.3934,.3881,.3827]])}
        self.bars=[{"ts":datetime.datetime.fromtimestamp(self.t-900*(120-i),datetime.timezone.utc).isoformat(),
                    "open":.4,"high":.41,"low":.38,"close":.399} for i in range(120)]
    def test_requires_history(self):
        with self.assertRaises(ValueError): render(self.row,self.bars[:9])
    def test_requires_aligned_close(self):
        bad=[dict(x) for x in self.bars]
        bad[-1]["ts"]=datetime.datetime.fromtimestamp(self.t+36000,datetime.timezone.utc).isoformat()
        with self.assertRaises(ValueError): render(self.row,bad)
    def test_full_bleed_dark_background(self):
        from matplotlib.image import imread
        path=render(self.row,self.bars)
        try:
            pixels=imread(path)
            h,w=pixels.shape[:2]
            # Telegram image viewer enlarges the entire PNG: no white margins.
            for y,x in [(3,3),(3,w-4),(h-4,3),(h-4,w-4)]:
                self.assertLess(float(max(pixels[y,x,:3])),0.20)
        finally:
            os.unlink(path)
    def test_valid_chart(self):
        path=render(self.row,self.bars)
        try:
            self.assertGreater(os.path.getsize(path),10000)
        finally:os.unlink(path)
if __name__=="__main__":unittest.main()
