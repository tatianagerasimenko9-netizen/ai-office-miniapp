import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from office_br.universe import eligible_symbols

class FuturesUniverseTests(unittest.TestCase):
    def test_perpetual_usdt_only(self):
        sample = {"symbols": [
            {"symbol":"ETHUSDT","status":"TRADING","contractType":"PERPETUAL","quoteAsset":"USDT","marginAsset":"USDT"},
            {"symbol":"BTCUSDT","status":"TRADING","contractType":"CURRENT_QUARTER","quoteAsset":"USDT","marginAsset":"USDT"},
            {"symbol":"DOGEUSDT","status":"BREAK","contractType":"PERPETUAL","quoteAsset":"USDT","marginAsset":"USDT"},
            {"symbol":"ETHUSDC","status":"TRADING","contractType":"PERPETUAL","quoteAsset":"USDC","marginAsset":"USDC"},
            {"symbol":"SOLUSDT","status":"TRADING","contractType":"PERPETUAL","quoteAsset":"USDT","marginAsset":"USDT"}]}
        self.assertEqual(eligible_symbols(sample), ("ETHUSDT", "SOLUSDT"))
    def test_fail_closed(self):
        with self.assertRaises(ValueError):
            eligible_symbols({"symbols":[]})
if __name__ == "__main__":
    unittest.main()
