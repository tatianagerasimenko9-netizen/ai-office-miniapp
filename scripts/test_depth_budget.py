#!/usr/bin/env python3
"""Стакан не з'їдає ліміти свічок: вимкнено за замовчуванням; короткий список; кеш; рознесення; окрема пауза; пауза свічок має пріоритет."""
import os
import sys
import time
from urllib.error import HTTPError
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_market_data as M  # noqa: E402

calls = []
book = {"bids": [["100", "10000"]], "asks": [["101", "10000"]]}


def fake(url, params, scope=""):
    calls.append((url, params.get("symbol"), scope))
    return book


M._http_get_json = fake
# 1. за замовчуванням вимкнено — жодних запитів
os.environ.pop("OFFICE_DEPTH_ENABLED", None)
r = M.fetch_order_book_walls("BTCUSDT")
assert calls == [] and r["description"] == "DOM недоступний" and r["reason"] == "вимкнено"
# 2. увімкнено, але лише короткий список
os.environ["OFFICE_DEPTH_ENABLED"] = "1"
os.environ["OFFICE_DEPTH_SYMBOLS"] = "BTCUSDT,ETHUSDT"
assert M.fetch_order_book_walls("XRPUSDT")["reason"] == "монета не в короткому списку" and calls == []
# 3. запит іде зі scope=depth; повтор — з кешу; наступна монета в межах 3 с — рознесення
M._DEPTH_LAST_REQ = 0.0
assert M.fetch_order_book_walls("BTCUSDT")["whale_bids"] and calls == [("https://fapi.binance.com/fapi/v1/depth", "BTCUSDT", "depth")]
assert M.fetch_order_book_walls("BTCUSDT")["whale_bids"] and len(calls) == 1, "кеш 60 с"
assert M.fetch_order_book_walls("ETHUSDT")["reason"] == "рознесення" and len(calls) == 1
M._DEPTH_LAST_REQ = time.time() - 10
assert M.fetch_order_book_walls("ETHUSDT")["whale_bids"] and len(calls) == 2
# 4. пауза свічок ф'ючерсів має пріоритет: стакан мовчить
M._DEPTH_CACHE.clear(); M._DEPTH_LAST_REQ = 0.0
M._BACKOFF_UNTIL = time.time() + 60
assert M.fetch_order_book_walls("BTCUSDT")["reason"] == "пауза" and len(calls) == 2
M._BACKOFF_UNTIL = 0.0
# 5. 429 на стакані ставить ТІЛЬКИ паузу стакана, не паузу свічок
M2 = M
M._http_get_json = M.__dict__.get("_orig") or None
import importlib  # noqa: E402

importlib.reload(M)   # повертаємо справжній _http_get_json
os.environ["OFFICE_DEPTH_ENABLED"] = "1"
os.environ["OFFICE_DEPTH_SYMBOLS"] = "BTCUSDT"


class R429:
    def __enter__(self):
        raise HTTPError("u", 429, "Too Many Requests", {"Retry-After": "40"}, io.BytesIO(b""))

    def __exit__(self, *a):
        return False


M.urlopen = lambda req, timeout=12: R429()
M._DEPTH_LAST_REQ = 0.0
r = M.fetch_order_book_walls("BTCUSDT")
assert r["description"] == "DOM недоступний"
assert M._DEPTH_BACKOFF_UNTIL > time.time() + 25, "своя пауза стакана"
assert M._BACKOFF_UNTIL == 0.0, "пауза свічок НЕ вмикається від стакана"
assert M.depth_stats()["rate_limited"] == 1 and M.fetch_order_book_walls("BTCUSDT")["reason"] == "пауза"
print("OK depth budget: off by default, short list, cache, spacing, own backoff, candles priority")
