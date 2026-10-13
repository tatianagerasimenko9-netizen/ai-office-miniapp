#!/usr/bin/env python3
"""Бюджет пам'яті: кеш свічок не росте без меж, протерміновані записи прибираються, активні лишаються; WS-потік не тримає зайвих барів; проби/етапи працюють."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["OFFICE_WS_KLINES"] = "0"
import office_market_data as MD  # noqa: E402
import office_runtime_guard as RG  # noqa: E402
import office_ws_klines as WS  # noqa: E402


def rows(n):
    return [{"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0, "ts": f"2026-01-01T00:{i % 60:02d}:00+00:00", "src": "binance_futures"} for i in range(n)]


def main():
    MD._CANDLE_CACHE.clear()
    MD._CANDLE_CACHE_STATS.update(evicted_expired=0, evicted_budget=0)
    now = time.time()
    # 1) протерміновані записи (старші за _MAX_STALE ТФ) прибираються при наступному записі
    MD._candle_cache_put(("OLD1USDT", "15m"), now - 3 * 3600, 300, rows(300))
    MD._candle_cache_put(("NEWUSDT", "15m"), now, 300, rows(300))
    assert ("OLD1USDT", "15m") not in MD._CANDLE_CACHE and ("NEWUSDT", "15m") in MD._CANDLE_CACHE
    assert MD._CANDLE_CACHE_STATS["evicted_expired"] == 1
    # 2) бюджет: сумарно > ліміту — найстаріші за часом запису видаляються, щойно записаний лишається
    MD._CANDLE_CACHE.clear()
    old_budget = MD._CANDLE_CACHE_MAX_ROWS
    MD._CANDLE_CACHE_MAX_ROWS = 2000
    try:
        for i in range(20):
            MD._candle_cache_put((f"S{i}USDT", "1h"), now - 100 + i, 500, rows(500))
        st = MD.candle_cache_stats()
        assert st["rows"] <= 2000, st
        assert ("S19USDT", "1h") in MD._CANDLE_CACHE, "найсвіжіший запис мусить лишитись"
        assert ("S0USDT", "1h") not in MD._CANDLE_CACHE, "найстаріший мусить піти"
        assert st["evicted_budget"] > 0
    finally:
        MD._CANDLE_CACHE_MAX_ROWS = old_budget
    # 3) оновлення активного ключа не збільшує кеш і не видаляє його
    MD._CANDLE_CACHE.clear()
    for _ in range(5):
        MD._candle_cache_put(("BTCUSDT", "15m"), now, 300, rows(300))
    assert len(MD._CANDLE_CACHE) == 1
    # 4) WS: тримаємо want+100, не 1500
    e = WS._new_entry(now)
    assert WS._keep_bars(e) == 600
    e["want"] = 1000
    assert WS._keep_bars(e) == 1100
    e["want"] = 1500
    assert WS._keep_bars(e) == WS._MAX_BARS
    WS._STORE.clear()
    WS._STORE[("ETHUSDT", "1m")] = e2 = WS._new_entry(now, acked=True)
    e2["want"] = 100
    e2["seeded"] = True
    for i in range(1000):
        WS._apply("ETHUSDT", "1m", {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "ts": f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00+00:00", "src": "binance_futures"})
    assert len(e2["bars"]) == 600, len(e2["bars"])
    assert WS.memory_stats()["bars"] == 600
    WS._STORE.clear()
    # 5) проби та етапи
    RG.register_probe("t", lambda: 7)
    with RG.stage("t.stage"):
        pass
    assert "t=7" in RG.probe_report() and "t.stage" in RG.stage_report(reset=True)
    RG.register_default_probes()
    assert "gc_objects=" in RG.probe_report()
    print("ok memory budget")


main()
