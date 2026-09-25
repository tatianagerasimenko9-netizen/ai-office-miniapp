#!/usr/bin/env python3
"""T8: lifecycle + DATA_UNAVAILABLE + T7 cold snapshot; пороги 80/90 не чіпаємо."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT, T0_ENTRY_BLOCK_PCT  # noqa: E402
from office_btc_liquidations import CREATES_ENTER, BtcForceOrderBook  # noqa: E402
from office_lifecycle import next_lifecycle_state  # noqa: E402
from office_session_radar import independent_flip_ok  # noqa: E402
from office_t7_health import classify_book_state, diagnose_force_order_snapshot  # noqa: E402
from office_t8_backtest import DATA_CONTROL, DATA_UNAVAILABLE, run_t8_backtest  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or T0_ENTRY_BLOCK_PCT != 90.0:
        return _fail("T0 90 frozen")
    if GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("80 frozen")
    if CREATES_ENTER:
        return _fail("T7 enter")

    miss = run_t8_backtest("/tmp/t8-no-such-ohlcv.json")
    if miss.data_status != DATA_UNAVAILABLE:
        return _fail("missing file must be DATA_UNAVAILABLE")
    if miss.wr_pct is not None or miss.stats_are_live_trading or miss.opens_orders:
        return _fail("unavailable must not fake WR")

    ctrl = ROOT / "fixtures" / "t6_backtest_control.json"
    rep = run_t8_backtest(ctrl)
    if rep.data_status != DATA_CONTROL:
        return _fail(f"control status {rep.data_status}")
    if rep.stats_are_live_trading or "не є торговою" not in (rep.note or "") and "NOT_LIVE" not in (rep.note or "") and "CONTROL" not in (rep.disclaimer or ""):
        if rep.stats_are_live_trading:
            return _fail("must not claim live stats")
    if rep.opens_orders:
        return _fail("orders")

    now = datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc)
    created = now - timedelta(seconds=10)
    w = next_lifecycle_state(
        current="WATCHING",
        price=83000,
        entry_low=82963,
        entry_high=83434,
        created_ts=created,
        now_ts=now,
    )
    if w["state"] != "ZONE_REACHED":
        return _fail(f"zone {w}")
    c = next_lifecycle_state(
        current="ZONE_REACHED",
        price=83000,
        entry_low=82963,
        entry_high=83434,
        created_ts=created,
        now_ts=now,
        confirmed=True,
        entry_blocked=False,
        day_used_pct=40.0,
    )
    if c["state"] != "CONFIRMED":
        return _fail(f"confirmed {c}")
    exp = next_lifecycle_state(
        current="WATCHING",
        price=80000,
        entry_low=82963,
        entry_high=83434,
        created_ts=now - timedelta(hours=5),
        now_ts=now,
    )
    if exp["state"] != "EXPIRED":
        return _fail(f"expired {exp}")
    inv = next_lifecycle_state(
        current="ZONE_REACHED",
        price=83000,
        entry_low=82963,
        entry_high=83434,
        created_ts=created,
        now_ts=now,
        invalidated=True,
        invalidate_reason="немає незалежного підтвердження",
    )
    if inv["state"] != "INVALIDATED":
        return _fail(f"inv {inv}")
    atr90 = next_lifecycle_state(
        current="ZONE_REACHED",
        price=83000,
        entry_low=82963,
        entry_high=83434,
        created_ts=created,
        now_ts=now,
        day_used_pct=91.0,
    )
    if atr90["state"] != "EXPIRED":
        return _fail("t0 expire")

    if independent_flip_ok(
        previous_direction="LONG",
        new_direction="SHORT",
        sweep={"bsl_sweep": False, "ssl_sweep": False},
        m5_ok=False,
        m1_ok=False,
        stop_hit=True,
    ):
        return _fail("flip on stop")

    cold = BtcForceOrderBook().snapshot()
    if cold.get("book_state") != "idle_cold":
        return _fail(f"cold {cold.get('book_state')}")
    d = diagnose_force_order_snapshot(cold)
    if d["state"] != "idle_cold" or d["needs_force_order_to_prove_ws"]:
        return _fail(f"diag {d}")
    if classify_book_state({"connected": False, "reconnects": 2, "last_error": "x"}) != "disconnected":
        return _fail("disconnected class")

    print("OK: test_t8_lifecycle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
