#!/usr/bin/env python3
"""T8: дворівневий скаут усього ринку. Топ % ≠ сетап. Без автоордера."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_market_scout import (  # noqa: E402
    CONTEXT_SEEDS,
    DATA_UNAVAILABLE,
    DEEP_SCAN_CAP,
    already_ran_without_entry,
    btc_context_only,
    promote_for_deep_scan,
    screen_futures_market,
    top_move_is_setup,
)
from office_radar import RADAR_SYMBOLS  # noqa: E402
from office_range_radar import T8_SCAN_UNIVERSE, radar_symbols_for_monitor  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _t(sym: str, ch: float, vol: float, last: float = 1.0, high: float = 1.1, low: float = 0.9) -> dict:
    return {
        "symbol": sym,
        "lastPrice": last,
        "priceChangePercent": ch,
        "quoteVolume": vol,
        "highPrice": high,
        "lowPrice": low,
    }


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0:
        return _fail("T0 90")
    if SIGNAL_THRESHOLD != 85:
        return _fail("Edge 85")
    if RADAR_SYMBOLS != ("BTCUSDT",):
        return _fail("T6 frozen")
    if T8_SCAN_UNIVERSE != CONTEXT_SEEDS:
        return _fail("universe is context seeds, not a 5-coin list")
    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("order")
    if top_move_is_setup(32.0):
        return _fail("30% gainer is not a setup")

    miss = screen_futures_market(None)
    if miss.data_status != DATA_UNAVAILABLE or miss.gainers:
        return _fail("empty ticker must be DATA_UNAVAILABLE")

    tickers = [
        _t("USDCUSDT", 1.0, 9e9),
        _t("BTCUSDT", 1.2, 2e10, last=83000, high=84000, low=82000),
        _t("XAUUSDT", 0.4, 8e8, last=2650, high=2660, low=2640),
        _t("AAAUSDT", 28.0, 9e6, last=2.0, high=2.4, low=1.6),
        _t("BBBUSDT", -19.0, 8e6, last=3.0, high=3.5, low=2.8),
        _t("DOGEUSDT", 6.0, 5e8),
        _t("PEPEUSDT", -7.0, 2e8),
        _t("WIFUSDT", 11.0, 7e7),
        _t("ILLIQUSDT", 40.0, 1000),
    ]
    # Розтягнути всесвіт: не лише великі імена.
    for i in range(40):
        tickers.append(_t(f"ALT{i}USDT", 0.3 + i * 0.01, 6e6 + i * 1e5))

    scr = screen_futures_market(tickers)
    if scr.data_status != "DATA_OK" or scr.screened < 40:
        return _fail(f"screen {scr.screened} {scr.data_status}")
    if any(r["symbol"] == "ILLIQUSDT" for r in scr.rows):
        return _fail("illiquid leaked")
    if any(r["symbol"] == "USDCUSDT" for r in scr.rows):
        return _fail("stable leaked")
    if scr.gainers[0]["symbol"] != "AAAUSDT" or scr.losers[0]["symbol"] != "BBBUSDT":
        return _fail("gainer/loser order")
    if scr.gainers[0]["qualifies_as_setup"] or scr.opens_position:
        return _fail("gainer treated as setup")
    if not scr.gold or scr.gold.get("source") != "binance_futures":
        return _fail(f"gold {scr.gold}")
    if btc_context_only(scr).get("copies_direction"):
        return _fail("btc copy")

    deep = promote_for_deep_scan(
        scr,
        extra_user_symbols=["MYCOINUSDT", "AAAUSDT"],
        active_watching=["WATCHUSDT"],
        cap=DEEP_SCAN_CAP,
    )
    if deep[0] != "MYCOINUSDT":
        return _fail(f"user request first {deep[:5]}")
    if "WATCHUSDT" not in deep:
        return _fail("active watching")
    if "AAAUSDT" not in deep or "BBBUSDT" not in deep:
        return _fail("movers not promoted")
    if "BTCUSDT" not in deep or "XAUUSDT" not in deep:
        return _fail("context seeds")
    if len(deep) > DEEP_SCAN_CAP:
        return _fail("cap")
    if "ILLIQUSDT" in deep:
        return _fail("illiquid in deep")

    # Без ticker все одно є якір + запит Тетяни — офіс не німіє до 5 монет.
    fallback = promote_for_deep_scan(miss, extra_user_symbols=["SOLUSDT"])
    if fallback[0] != "SOLUSDT" or "BTCUSDT" not in fallback:
        return _fail(f"fallback {fallback}")

    if not already_ran_without_entry(direction="LONG", entry=100, price=104, sl=99):
        return _fail("chase long")
    if already_ran_without_entry(direction="LONG", entry=100, price=100.4, sl=99):
        return _fail("false chase")

    combo = radar_symbols_for_monitor(RADAR_SYMBOLS, deep_symbols=deep)
    if combo[0] != "BTCUSDT":
        return _fail("t6 first")
    if "ETHUSDT" in T8_SCAN_UNIVERSE:
        return _fail("fixed alt list must be gone")

    print("OK: test_t8_market_scout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
