#!/usr/bin/env python3
"""ATR 80 vs 90: ролі різні, числа заморожені, NO_TRADE — правило."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import (  # noqa: E402
    GERCHIK_TREND_ENTRY_BLOCK_PCT,
    T0_ENTRY_BLOCK_PCT,
    classify_atr_day_used,
    explain_atr_day_used,
    new_daily_bar_resets_atr,
    no_trade_means_price_wont_move,
    probability_no_trade_payload,
)
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("80 frozen")
    if T0_ENTRY_BLOCK_PCT != 90.0 or ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0:
        return _fail("90 frozen")
    if new_daily_bar_resets_atr() or no_trade_means_price_wont_move():
        return _fail("reset/forecast flags")
    mid = classify_atr_day_used(85.1)
    if mid["t0_entry_blocked"]:
        return _fail("85.1 must not T0-block")
    if not mid["gerchik_entry_blocked"] or not mid["search_continues"]:
        return _fail("85.1 gerchik block + search")
    if "не прогноз" not in mid["label"] and "ринок зупинився" not in mid["label"]:
        return _fail("label must deny dead market")
    t0 = classify_atr_day_used(91.0)
    if not t0["t0_entry_blocked"] or not t0["search_continues"]:
        return _fail("91 T0 block still searches")
    payload = probability_no_trade_payload(85.1)
    if payload["no_trade_prob"] != 100 or payload["no_trade_is_price_forecast"]:
        return _fail("NO_TRADE is rule not forecast")
    if "правило" not in payload["reason"].lower() and "вето" not in payload["reason"].lower():
        return _fail(f"reason wording {payload['reason']}")
    exp = explain_atr_day_used(120.7)
    if exp.get("excess_pct_over_atr") != 20.7 or exp.get("more_than_double_atr"):
        return _fail(f"120.7 explain {exp}")
    if exp.get("new_d1_is_entry") or new_daily_bar_resets_atr():
        return _fail("D1 is not entry")
    print("OK: test_atr_policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
