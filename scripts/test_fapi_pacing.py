#!/usr/bin/env python3
"""fapi: рівномірний потік (≥60 мс), контроль вагою X-MBX-USED-WEIGHT-1M (пауза до кінця хвилини до 429)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_market_data as M  # noqa: E402

class H(dict):
    pass

class Resp:
    def __init__(self, weight):
        self.headers = H({"X-MBX-USED-WEIGHT-1M": str(weight)})
    def read(self):
        return b"[]"
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

W = {"v": 100}
M.urlopen = lambda req, timeout=12: Resp(W["v"])
M._STARTED_AT = time.time() - 1000   # поза стартовим розгоном
t0 = time.time()
for _ in range(6):
    M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {})
assert time.time() - t0 >= 5 * 0.055, "запити рознесено ≥60 мс"
assert M.source_health()["used_weight_1m"] == 100 and M.backoff_left() == 0
W["v"] = 1900
M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {})
assert M.backoff_left() > 0 and M.source_health()["weight_pauses"] == 1, M.source_health()
# резервні джерела темпом і вагою не керуються
M._BACKOFF_UNTIL = 0.0
t1 = time.time()
for _ in range(5):
    M._http_get_json("https://data-api.binance.vision/api/v3/klines", {})
assert time.time() - t1 < 0.2 and M.backoff_left() == 0
print("OK fapi pacing: 60ms spacing, weight-aware pause before 429, fallbacks unaffected")

# стартовий розгін: на Render перші 3 хв процесу — ≥250 мс між запитами; поза Render (тести/CI) — ні
os.environ.pop('RENDER', None)
M._STARTED_AT = time.time()
t_ = time.time()
for _ in range(4):
    M._http_get_json('https://fapi.binance.com/fapi/v1/klines', {})
assert time.time() - t_ < 0.6, 'поза Render розгону немає'
os.environ['RENDER'] = 'true'
M._BACKOFF_UNTIL = 0.0
W["v"] = 100
t2 = time.time()
for _ in range(4):
    M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {})
assert time.time() - t2 >= 3 * 0.24, "стартовий темп"
print("OK fapi startup ramp")
