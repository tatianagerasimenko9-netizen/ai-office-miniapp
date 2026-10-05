#!/usr/bin/env python3
"""Облік прямих (aiohttp) запитів до fapi і реалістична оцінка ваги: повний список ticker/24hr = 40, по символу = 1; лише облік, поведінка не змінюється."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
import office_market_data as md  # noqa: E402

FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)
        print("FAIL:", msg)


check(md._endpoint_weight("24hr", {}) == 40 and md._endpoint_weight("24hr", {"symbol": "BTCUSDT"}) == 1, "24hr: без symbol 40, з symbol 1")
check(md._endpoint_weight("premiumIndex", {}) == 10 and md._endpoint_weight("premiumIndex", {"symbol": "X"}) == 1, "premiumIndex: без symbol 10")
check(md._endpoint_weight("depth", {"limit": 100}) == 5 and md._endpoint_weight("forceOrders", {}) == 50, "depth 100 = 5; forceOrders = 50")


class H(dict):
    pass


md._DIRECT.clear()
md.note_direct("scanner_cycle", "https://fapi.binance.com/fapi/v1/ticker/24hr", H({"X-MBX-USED-WEIGHT-1M": "1203"}))
md.note_direct("scanner_cycle", "https://fapi.binance.com/fapi/v1/ticker/24hr", H({"X-MBX-USED-WEIGHT-1M": "800"}))
md.note_direct("mark_price", "https://fapi.binance.com/fapi/v1/premiumIndex", None, {"symbol": "BTCUSDT"})
d = md._DIRECT
check(d["scanner_cycle|24hr"]["calls"] == 2 and d["scanner_cycle|24hr"]["weight_est"] == 80 and d["scanner_cycle|24hr"]["max_used_weight_1m"] == 1203, f"повний список: 2 виклики = 80, максимум ваги IP 1203: {d}")
check(d["mark_price|premiumIndex"]["weight_est"] == 1, "по символу = 1")
check("direct_fapi" in md.source_health(), "звіт іде в [data] binance")
md.note_direct("x", "not-a-fapi-url")   # не падає
# _count_rest тепер оцінює повний 24hr як 40
md._HEALTH.pop("rest_by", None)
md._HEALTH["weight_est"] = 0
md._count_rest("https://fapi.binance.com/fapi/v1/ticker/24hr", {})
check(md._HEALTH["weight_est"] == 40, f"_count_rest: повний 24hr = 40: {md._HEALTH['weight_est']}")
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)
