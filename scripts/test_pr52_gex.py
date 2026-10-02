#!/usr/bin/env python3
"""PR52: GEX Deribit BTC/ETH — DATA_UNAVAILABLE без ордерів і без чату."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_gex import gex_log_line, summarize_deribit_book  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or SIGNAL_THRESHOLD != 85 or MIN_RR < 1.5:
        return _fail("frozen")
    empty = summarize_deribit_book([], currency="BTC")
    if empty.get("status") != "DATA_UNAVAILABLE" or empty.get("ok"):
        return _fail(f"empty {empty}")
    eth = summarize_deribit_book(None, currency="ETH")
    if eth.get("status") != "DATA_UNAVAILABLE":
        return _fail(f"eth {eth}")
    rows = [
        {
            "instrument_name": "BTC-26SEP26-100000-C",
            "open_interest": 10.0,
            "greeks": {"gamma": 0.001},
        },
        {
            "instrument_name": "BTC-26SEP26-100000-P",
            "open_interest": 8.0,
            "greeks": {"gamma": 0.002},
        },
    ]
    ok = summarize_deribit_book(rows, currency="BTC")
    if not ok.get("ok") or ok.get("n") != 2:
        return _fail(f"ok {ok}")
    if abs(float(ok["call_gex"]) - 0.01) > 1e-9:
        return _fail(f"call {ok}")
    if abs(float(ok["put_gex"]) - 0.016) > 1e-9:
        return _fail(f"put {ok}")
    line = gex_log_line({"BTC": ok, "ETH": empty})
    if "[gex]" not in line or "DATA_UNAVAILABLE" not in line:
        return _fail(line)
    if "forceOrder" in line:
        return _fail("no forceOrder in gex log")
    print("OK: test_pr52_gex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
