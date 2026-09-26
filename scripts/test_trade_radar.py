#!/usr/bin/env python3
"""T6: радар рівнів — WATCHING без підтвердження; SIGNAL лише з карткою, без позиції."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_radar import (  # noqa: E402
    MIN_RR,
    SL_BUFFER_PCT,
    classify_proximity,
    cluster_sr_levels,
    detect_sweep_from_candles,
    evaluate_radar,
    format_radar_card,
    m15_confirmation,
)
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl) -> dict:
    return {"open": o, "high": h, "low": l, "close": cl}


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0:
        return _fail("T0 ATR must stay 90")
    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("T1: radar/scanner must not open position")
    if MIN_RR < 1.5 or SL_BUFFER_PCT <= 0:
        return _fail("risk constants")

    daily = []
    for _ in range(8):
        daily.append(_c(100, 110, 90, 100))
        daily.append(_c(100, 111, 89.5, 101))
    levels = cluster_sr_levels(daily)
    types = {x["type"] for x in levels}
    if "support" not in types or "resistance" not in types:
        return _fail("sr types")
    if classify_proximity(100.0, 100.05) != "reached":
        return _fail("reached")
    if classify_proximity(100.0, 100.25) != "approaching":
        return _fail("approaching")
    if classify_proximity(100.0, 110.0) != "away":
        return _fail("away")

    # SSL sweep: last wick below prev lows, close back above
    sweep_ssl = [
        _c(10, 10.2, 9.8, 10.0),
        _c(10, 10.3, 9.85, 10.1),
        _c(10.0, 10.1, 9.5, 9.95),
    ]
    sw = detect_sweep_from_candles(sweep_ssl)
    if not sw["ssl_sweep"] or sw["direction_hint"] != "LONG":
        return _fail("ssl sweep")
    if not m15_confirmation([_c(9.9, 10.2, 9.9, 10.15)], direction="LONG", level=9.8):
        return _fail("m15 long confirm")
    if m15_confirmation([_c(10.2, 10.3, 10.1, 10.0)], direction="LONG", level=9.8):
        return _fail("m15 must reject")

    no_confirm = evaluate_radar(
        symbol="BTCUSDT",
        price=9.95,
        daily_candles=daily,
        sweep_candles=sweep_ssl,
        m15_candles=[_c(10.2, 10.3, 9.4, 9.5)],
        day_used_pct=40.0,
        in_kill_zone=True,
    )
    if no_confirm.status != "WATCHING" or no_confirm.opens_position:
        return _fail("no confirm = watching")
    if "не сигнал" not in format_radar_card(no_confirm).lower() and "WATCHING" not in format_radar_card(no_confirm):
        return _fail("watching card")

    ok = evaluate_radar(
        symbol="BTCUSDT",
        price=10.0,
        daily_candles=daily,
        sweep_candles=sweep_ssl,
        m15_candles=[_c(9.9, 10.2, 9.9, 10.2)],
        day_used_pct=40.0,
        in_kill_zone=True,
    )
    if ok.status != "SIGNAL" or ok.opens_position:
        return _fail(f"confirmed signal {ok.status} {ok.reason}")
    if not ok.card or ok.card["sl"] >= ok.card["entry"]:
        return _fail("long sl below entry")
    if ok.card["rr"] < 1.5:
        return _fail("rr")
    txt = format_radar_card(ok)
    if "Entry:" not in txt or "не відкрита позиція" not in txt:
        return _fail("signal card text")

    atr = evaluate_radar(
        symbol="BTCUSDT",
        price=10.0,
        daily_candles=daily,
        sweep_candles=sweep_ssl,
        m15_candles=[_c(9.9, 10.2, 9.9, 10.2)],
        day_used_pct=91.0,
        in_kill_zone=True,
    )
    if atr.status != "WATCHING" or "ATR" not in atr.reason:
        return _fail("T0 atr watch")

    blocked = evaluate_radar(
        symbol="BTCUSDT",
        price=10.0,
        daily_candles=daily,
        sweep_candles=sweep_ssl,
        m15_candles=[_c(9.9, 10.2, 9.9, 10.2)],
        day_used_pct=40.0,
        bot_action="BLOCKED",
        in_kill_zone=True,
    )
    if blocked.status != "WATCHING" or "BLOCKED" not in blocked.reason:
        return _fail("T5 blocked")

    offkz = evaluate_radar(
        symbol="BTCUSDT",
        price=10.0,
        daily_candles=daily,
        sweep_candles=sweep_ssl,
        m15_candles=[_c(9.9, 10.2, 9.9, 10.2)],
        day_used_pct=40.0,
        in_kill_zone=False,
        utc_now=datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
    )
    if offkz.status != "SIGNAL":
        return _fail(f"24/7 scan outside kz {offkz.status} {offkz.reason}")

    manip = evaluate_radar(
        symbol="BTCUSDT",
        price=10.0,
        daily_candles=daily,
        sweep_candles=sweep_ssl,
        m15_candles=[_c(9.9, 10.2, 9.9, 10.2)],
        day_used_pct=40.0,
        in_kill_zone=True,
        utc_now=datetime(2026, 9, 25, 6, 5, tzinfo=timezone.utc),
    )
    if manip.status != "WATCHING" or "маніпуляції" not in manip.reason:
        return _fail(f"manip window {manip.status} {manip.reason}")

    print("OK: test_trade_radar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
