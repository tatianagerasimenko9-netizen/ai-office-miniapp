#!/usr/bin/env python3
"""Сесійний радар: типи сетапів, M1, переворот лише з підтвердженням, без позиції."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_session_radar import (  # noqa: E402
    independent_flip_ok,
    evaluate_session_radar,
    session_at_utc,
)
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl) -> dict:
    return {"open": o, "high": h, "low": l, "close": cl}


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0:
        return _fail("T0 90")
    if session_at_utc(datetime(2026, 1, 15, 2, 0, tzinfo=timezone.utc)) != "asia":
        return _fail("asia")
    if session_at_utc(datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)) != "london":
        return _fail("london")
    ny = session_at_utc(datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc))
    if ny not in ("ny", "london_ny_overlap"):
        return _fail(f"ny {ny}")

    sweep_ssl = [_c(10, 10.2, 9.8, 10.0), _c(10, 10.3, 9.85, 10.1), _c(10.0, 10.1, 9.5, 9.95)]
    m15_ok = [_c(9.9, 10.2, 9.9, 10.15)]
    if independent_flip_ok(
        previous_direction="LONG",
        new_direction="SHORT",
        sweep={"bsl_sweep": False, "ssl_sweep": False},
        m5_ok=False,
        m1_ok=False,
        stop_hit=True,
    ):
        return _fail("stop alone must not flip")
    res = evaluate_session_radar(
        symbol="BTCUSDT",
        price=9.95,
        level_price=9.8,
        sweep_candles=sweep_ssl,
        m15_candles=[_c(10.2, 10.3, 9.4, 9.5)],
        utc_now=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc),
        day_used_pct=40.0,
    )
    if res.status != "WATCHING" or res.opens_position:
        return _fail(f"no confirm watching {res}")
    confirmed = evaluate_session_radar(
        symbol="BTCUSDT",
        price=10.15,
        level_price=9.8,
        sweep_candles=sweep_ssl,
        m15_candles=m15_ok,
        utc_now=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc),
        day_used_pct=40.0,
    )
    if confirmed.status != "SIGNAL" or confirmed.opens_position or not confirmed.card:
        return _fail(f"confirm card {confirmed}")
    atr85 = evaluate_session_radar(
        symbol="BTCUSDT",
        price=10.15,
        level_price=9.8,
        sweep_candles=sweep_ssl,
        m15_candles=m15_ok,
        day_used_pct=85.1,
        utc_now=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc),
    )
    if atr85.status != "WATCHING" or not atr85.search_continues or not atr85.entry_blocked:
        return _fail("85.1 keep watching + search")
    print("OK: test_session_radar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
