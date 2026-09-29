"""Резервні свічки: при 429/збої fapi — спот Binance, потім Bybit; вимкнення; пауза fapi не блокує резерв."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_market_data as m

calls = []
def fake(url, params):
    calls.append(url)
    if "fapi.binance.com" in url:
        m._BACKOFF_UNTIL = __import__("time").time() + 30
        raise m.RateLimited(30)
    if "vision" in url:
        return [[1700000000000 + i * 900000, "1", "2", "0.5", "1.5", "10"] for i in range(5)]
    raise AssertionError("bybit must not be reached when vision works")

m._http_get_json_orig = m._http_get_json
m._http_get_json = fake
m.reset_market_cache()
c = m.fetch_candles("BTC", "15m", 3)
assert isinstance(c, list) and len(c) == 3 and c[-1]["close"] == 1.5, c
assert m._HEALTH["fallback_src"] == "binance_spot_vision" and m._HEALTH["fallback_used"] == 1

def fake2(url, params):
    if "fapi" in url or "vision" in url:
        raise RuntimeError("down")
    return {"result": {"list": [["1700000900000", "1", "2", "0.5", "1.6", "7", "0"], ["1700000000000", "1", "2", "0.5", "1.4", "8", "0"]]}}
m._http_get_json = fake2
m.reset_market_cache()
c = m.fetch_candles("ETH", "1h", 5)
assert [x["close"] for x in c] == [1.4, 1.6] and m._HEALTH["fallback_src"] == "bybit_linear", c

os.environ["OFFICE_CANDLE_FALLBACK"] = "0"
m.reset_market_cache()
assert m.fetch_candles("SOL", "1h", 5) == {}
del os.environ["OFFICE_CANDLE_FALLBACK"]

# реальна _http_get_json: пауза лише для fapi
m._http_get_json = m._http_get_json_orig
m._BACKOFF_UNTIL = __import__("time").time() + 30
try:
    m._http_get_json("https://fapi.binance.com/x", {})
    raise SystemExit("fapi must be paused")
except m.RateLimited:
    pass
m.reset_market_cache()
print("OK candle fallback: vision -> bybit, disable flag, fapi pause does not block fallback")

# --- джерело не змішується непомітно: ф'ючерсний SEND не підтверджується за чужим ринком ---
import time as _t
from office_feed_quality import gate_send_on_fresh_data
from datetime import datetime, timezone
m._http_get_json = fake  # fapi 429 → spot vision
m.reset_market_cache(); m._FALLBACK_AT.clear()
now_ms = int(_t.time() // 900 * 900 * 1000)
def fake_fresh(url, params):
    if "fapi.binance.com" in url:
        raise m.RateLimited(30)
    return [[now_ms - (4 - i) * 900000, "1", "2", "0.5", "1.5", "10"] for i in range(5)]
m._http_get_json = fake_fresh
c = m.fetch_candles("BTCUSDT", "15m", 5)
assert c and all(x["src"] == "binance_spot_vision" for x in c)
assert m.fallback_recent("BTC") == "binance_spot_vision"
cyc = {"send": True, "action": "SEND", "symbol": "BTCUSDT"}
g = gate_send_on_fresh_data(cyc, c, interval="15m")
assert g["send"] is False and g["action"] == "WAIT" and "резервного ринку" in g["reason"] and g["data_source"] == "binance_spot_vision", g
# ф'ючерсні свічки без резервного сліду → шлях не заблоковано цим правилом
m._FALLBACK_AT.clear()
fut = [{"open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1, "ts": datetime.fromtimestamp((now_ms - (4 - i) * 900000) / 1000, tz=timezone.utc).isoformat(), "src": m.FUTURES_SRC} for i in range(5)]
g2 = gate_send_on_fresh_data({"send": True, "action": "SEND", "symbol": "BTCUSDT"}, fut, interval="15m")
assert "резервного ринку" not in str(g2.get("reason") or ""), g2
# лише слід у пам'яті (ціни іншого ринку віддавались недавно) теж блокує
m._FALLBACK_AT["BTCUSDT"] = (_t.time(), "bybit_linear")
g3 = gate_send_on_fresh_data({"send": True, "action": "SEND", "symbol": "BTCUSDT"}, fut, interval="15m")
assert g3["send"] is False and g3["data_source"] == "bybit_linear"
m.reset_market_cache(); m._FALLBACK_AT.clear()
print("OK source tagging: fallback candles tagged, futures SEND blocked on other market, futures path untouched")
