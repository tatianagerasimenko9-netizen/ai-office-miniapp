#!/usr/bin/env python3
"""Свічки Binance: кеш, 429 → пауза, віддача останнього кешу (≤20 хв) при збої, чесний {} без кешу. Офлайн (підміна HTTP)."""
import io
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("OFFICE_CANDLE_CACHE", None)
import office_market_data as MD  # noqa: E402

calls = []


def klines(n):
    base = 1_780_000_000_000
    return [[base + i * 900_000, "1", "2", "0.5", "1.5", "10"] for i in range(n)]


def fake_ok(url, params):
    calls.append((params["symbol"], params["interval"], params["limit"]))
    return klines(int(params["limit"]))


MD.reset_market_cache()
orig = MD._http_get_json
MD._http_get_json = fake_ok
try:
    a = MD.fetch_candles("SOL", "15m", 30)
    b = MD.fetch_candles("SOLUSDT", "15m", 20)          # той самий набір з кешу, без другого запиту
    assert len(a) == 30 and len(b) == 20 and len(calls) == 1, calls
    c = MD.fetch_candles("SOLUSDT", "15m", 60)          # потрібно більше, ніж у кеші → новий запит із більшим лімітом
    assert len(c) == 60 and len(calls) == 2 and calls[-1][2] == 60
    assert len(MD.fetch_candles("SOLUSDT", "15m", 30)) == 30 and len(calls) == 2, "менший ліміт береться з більшого кешу"

    # збій джерела: віддаємо останній кеш (не старший 20 хв), лічильник stale_served росте
    def boom(url, params):
        raise RuntimeError("net down")
    MD._http_get_json = boom
    key = ("SOLUSDT", "15m")
    t, lim, rows = MD._CANDLE_CACHE[key]
    MD._CANDLE_CACHE[key] = (time.time() - 300, lim, rows)   # TTL 60 с минув, але ще < 20 хв
    got = MD.fetch_candles("SOLUSDT", "15m", 10)
    assert len(got) == 10 and MD.source_health()["stale_served"] == 1
    MD._CANDLE_CACHE[key] = (time.time() - 3600, lim, rows)  # M15: старіше 30 хв — не віддаємо застаріле
    assert MD.fetch_candles("SOLUSDT", "15m", 10) == {}
    # повільні таймфрейми переживають довше: H1 із кешу 2 год тому ще віддається, D1 — 30 год тому теж
    MD._CANDLE_CACHE[("SOLUSDT", "1h")] = (time.time() - 2 * 3600, 5, rows)
    assert len(MD.fetch_candles("SOLUSDT", "1h", 5)) == 5
    MD._CANDLE_CACHE[("SOLUSDT", "1d")] = (time.time() - 30 * 3600, 5, rows)
    assert len(MD.fetch_candles("SOLUSDT", "1d", 5)) == 5
    MD._CANDLE_CACHE[("SOLUSDT", "1h")] = (time.time() - 5 * 3600, 5, rows)
    assert MD.fetch_candles("SOLUSDT", "1h", 5) == {}
    # монети без кешу при збої → {} (не вигадуємо)
    assert MD.fetch_candles("NEWCOINUSDT", "1h", 5) == {}
    # порожня відповідь не кешується
    MD._http_get_json = lambda u, p: []
    assert MD.fetch_candles("EMPTYUSDT", "1h", 5) == {} and ("EMPTYUSDT", "1h") not in MD._CANDLE_CACHE
finally:
    MD._http_get_json = orig

# 429: Retry-After → пауза для всіх запитів до Binance, без нових HTTP-викликів
MD.reset_market_cache()
n_open = []


class FakeResp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def urlopen_429(req, timeout=12):
    n_open.append(1)
    raise HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "40"}, io.BytesIO(b""))


os.environ["OFFICE_CANDLE_FALLBACK"] = "0"  # тут перевіряємо саме паузу основного джерела
MD.urlopen = urlopen_429
try:
    assert MD.fetch_candles("ETHUSDT", "15m", 10) == {}
    assert MD.source_health()["rate_limited"] == 1 and 30 < MD.source_health()["backoff_left_sec"] <= 40
    assert MD.fetch_candles("BTCUSDT", "1h", 10) == {} and len(n_open) == 1, "у паузі нових запитів до Binance немає"
finally:
    MD.urlopen = __import__("urllib.request", fromlist=["urlopen"]).urlopen
    MD.reset_market_cache()
print("OK market data resilience: cache, one request for many readers, 429 backoff, stale-serve ≤20 min, honest empty")
