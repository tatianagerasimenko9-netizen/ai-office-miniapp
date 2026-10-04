#!/usr/bin/env python3
"""Інструментація навантаження Binance: причини промахів WS-тикера і хто просить свічки. Лише облік — відповіді даних не змінюються."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OFFICE_WS_TICKER"] = "1"
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
import office_market_data as md  # noqa: E402
import office_ws_ticker as wt  # noqa: E402

FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)
        print("FAIL:", msg)


wt._ensure_thread = lambda: None
wt.reset_for_tests()
now = time.time()
wt._TICK["FRESHUSDT"] = {"c": 2.0, "o": 1.0, "h": 2.1, "l": 0.9, "q": 5.0, "at": now}
wt._TICK["OLDUSDT"] = {"c": 2.0, "o": 1.0, "h": 2.1, "l": 0.9, "q": 5.0, "at": now - 75}
wt._TICK["NOOPENUSDT"] = {"c": 2.0, "o": 0.0, "h": 2.1, "l": 0.9, "q": 5.0, "at": now}
check(wt.get("FRESH") is not None, "свіжий запис — влучання")
check(wt.get("OLD") is None and wt.get("NOOPEN") is None and wt.get("GONE") is None, "три промахи")
st = wt.stats()["miss_why"]
check(st["stale"] == 1 and st["no_open"] == 1 and st["symbol_missing"] == 1, f"причини розрізняються: {st}")
check(74 <= (st["stale_age_s"]["p50"] or 0) <= 77 and st["stale_top"][0][0] == "OLDUSDT", f"вік застарілого запису: {st}")
check(wt.get("OLD", max_age=120) is not None, "TTL не змінено: за ширшого max_age запис придатний")

md._CALLERS.clear()


def consumer():
    md._note_call("15m", "AAAUSDT", "rest")
    md._note_call("15m", "BBBUSDT", "ws")


consumer()
rep = md.callers_report()
k = [x for x in rep if x.startswith("15m|test_rest_instrumentation.py:consumer")]
check(len(k) == 1 and rep[k[0]]["rest"] == 1 and rep[k[0]]["ws"] == 1 and rep[k[0]]["syms"] == 2, f"caller визначено (файл:функція) з розбивкою rest/ws/cache: {rep}")
check("klines_callers" in md.source_health(), "звіт іде в [data] binance")
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)
