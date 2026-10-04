#!/usr/bin/env python3
"""Пауза ваги Binance: звичайні запити чекають, «життя READY» (priority) проходить до жорсткої межі 2200; 429 і вага ≥ 2200 зупиняють усіх."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_market_data as M  # noqa: E402


class Hdr(dict):
    pass


M.reset_market_cache()
M._FAPI_GAP = 0.0
M._RAMP_GAP = 0.0
M._note_weight(Hdr({"X-MBX-USED-WEIGHT-1M": "1850"}))
assert M._SOFT_UNTIL > time.time() and M._BACKOFF_UNTIL == 0.0, "вага 1850 → лише м'яка пауза"


class Resp:
    headers = {"X-MBX-USED-WEIGHT-1M": "1850"}

    def read(self):
        return b"[]"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


M.urlopen = lambda *a, **k: Resp()   # без мережі
try:
    M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {"symbol": "X"})
    raise SystemExit("FAIL: звичайний запит мав чекати м'яку паузу")
except M.RateLimited:
    pass
with M.priority():
    assert M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {"symbol": "X"}) == [], "priority проходить м'яку паузу"
try:
    M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {"symbol": "X"})
    raise SystemExit("FAIL: після виходу з priority пауза знову діє")
except M.RateLimited:
    pass
assert M.backoff_left() > 0

M.reset_market_cache()
M._note_weight(Hdr({"X-MBX-USED-WEIGHT-1M": "2250"}))
assert M._BACKOFF_UNTIL > time.time(), "вага ≥ 2200 → жорстка пауза"
with M.priority():
    try:
        M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {"symbol": "X"})
        raise SystemExit("FAIL: priority не обходить жорстку паузу")
    except M.RateLimited:
        pass
M.reset_market_cache()
M._note_rate_limited = None
M.note_rate_limited(30)
with M.priority():
    try:
        M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {"symbol": "X"})
        raise SystemExit("FAIL: 429 зупиняє і priority")
    except M.RateLimited:
        pass
M.reset_market_cache()
print("OK priority lane: м'яка пауза ваги не затримує життя READY; жорстка пауза й 429 зупиняють усіх")

# облік REST: за ТФ і оцінка ваги нашого процесу
M.reset_market_cache()
M._HEALTH.pop("rest_by", None)
M._HEALTH["weight_est"] = 0
M._FAPI_GAP = 0.0
M._RAMP_GAP = 0.0
class Resp2(Resp):
    headers = {"X-MBX-USED-WEIGHT-1M": "100"}


M.urlopen = lambda *a, **k: Resp2()
M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {"symbol": "X", "interval": "1m", "limit": 30})
M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {"symbol": "X", "interval": "1m", "limit": 360})
M._http_get_json("https://fapi.binance.com/fapi/v1/klines", {"symbol": "X", "interval": "15m", "limit": 1000})
M._http_get_json("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": "X"})
assert M._HEALTH["rest_by"] == {"klines_1m": 2, "klines_15m": 1, "premiumIndex": 1}, M._HEALTH["rest_by"]
assert M._HEALTH["weight_est"] == 1 + 2 + 10 + 1, M._HEALTH["weight_est"]
print("OK rest accounting: по ТФ і оцінка ваги процесу")
