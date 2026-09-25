#!/usr/bin/env python3
"""T8: lifecycle + DATA_UNAVAILABLE + T7 cold snapshot; пороги 80/90/85 не чіпаємо."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT, T0_ENTRY_BLOCK_PCT  # noqa: E402
from office_bridge import _fetchall, init_office_db  # noqa: E402
from office_btc_liquidations import CREATES_ENTER, BtcForceOrderBook  # noqa: E402
from office_desk_state import build_desk_state  # noqa: E402
from office_lifecycle import LifecycleTrace, record_next_opportunity, next_lifecycle_state  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_paper_trading import run_session_paper  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_session_radar import independent_flip_ok  # noqa: E402
from office_t6_backtest import closed_asof, load_ohlcv_file, simulate_exit_on_bar  # noqa: E402
from office_t7_health import classify_book_state, diagnose_force_order_snapshot  # noqa: E402
from office_t8_backtest import DATA_CONTROL, DATA_UNAVAILABLE, run_t8_backtest  # noqa: E402
from office_watching_dedup import apply_skip_watching_gate, record_skip_if_valid  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402
from office_radar import RADAR_SYMBOLS  # noqa: E402
from office_market_scout import CONTEXT_SEEDS, top_move_is_setup  # noqa: E402
from office_range_radar import T8_SCAN_UNIVERSE  # noqa: E402
from office_external_signal import VERDICT_CONFIRMED  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or T0_ENTRY_BLOCK_PCT != 90.0:
        return _fail("T0 90 frozen")
    if GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("80 frozen")
    if SIGNAL_THRESHOLD != 85:
        return _fail("Edge 85 frozen")
    if RADAR_SYMBOLS != ("BTCUSDT",):
        return _fail("T6 symbols frozen")
    if T8_SCAN_UNIVERSE != CONTEXT_SEEDS:
        return _fail("T8 universe is scout seeds")
    if top_move_is_setup(30.0):
        return _fail("top move is not setup")
    if VERDICT_CONFIRMED == "ENTER":
        return _fail("verdict is not enter")
    if CREATES_ENTER:
        return _fail("T7 enter")
    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("auto order")

    miss = run_t8_backtest("/tmp/t8-no-such-ohlcv.json")
    if miss.data_status != DATA_UNAVAILABLE:
        return _fail("missing file must be DATA_UNAVAILABLE")
    if miss.wr_pct is not None or miss.stats_are_live_trading or miss.opens_orders:
        return _fail("unavailable must not fake WR")
    if miss.avg_r_after_costs is not None or miss.max_drawdown_r is not None:
        return _fail("unavailable must omit R/DD")

    ctrl = ROOT / "fixtures" / "t6_backtest_control.json"
    rep = run_t8_backtest(ctrl)
    if rep.data_status != DATA_CONTROL:
        return _fail(f"control status {rep.data_status}")
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

    tr = LifecycleTrace(symbol="ETHUSDT")
    record_next_opportunity(
        tr,
        ts=now.isoformat(),
        setup_type="sweep_reclaim",
        direction="SHORT",
        session="london",
        reason="після SKIP",
    )
    if not tr.next_opportunity or tr.opens_position:
        return _fail("next after skip")

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
    if d.get("idle_cold_means_no_liquidations") is not False:
        return _fail("idle_cold must not mean no liquidations")
    if "ліквідац" not in d["why_connected_false"].lower():
        return _fail("diag must mention liquidations")
    if classify_book_state({"connected": False, "reconnects": 2, "last_error": "x"}) != "disconnected":
        return _fail("disconnected class")

    data = load_ohlcv_file(ctrl)
    asof = datetime(2026, 1, 15, 13, 15, tzinfo=timezone.utc)
    m15 = closed_asof(data["timeframes"]["15m"], "15m", asof)
    if any(float(c["close"]) >= 199 for c in m15):
        return _fail("look-ahead")
    if simulate_exit_on_bar(side="SHORT", sl=108.3, tp=104.8, high=109.0, low=103.0) != "SL_CONSERVATIVE":
        return _fail("same-bar SL+TP")

    db = str(Path(tempfile.mkdtemp()) / "t8.db")
    init_office_db(db)
    before = _fetchall(db, "SELECT COUNT(*) FROM trade_journal")[0][0]
    paper = run_session_paper(str(ctrl))
    after = _fetchall(db, "SELECT COUNT(*) FROM trade_journal")[0][0]
    if before != after or paper.opens_live_journal or paper.kind != "paper":
        return _fail("paper leaked into journal")
    st = build_desk_state(
        db,
        watching_rows=[],
        journal_rows=[
            {
                "trade_id": "pos-1",
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "status": "OPEN",
                "entry_reason": "explicit /position by owner",
            }
        ],
        paper_trades=[{"symbol": "BTCUSDT"}],
    )
    if st["layers"]["positions_live"][0]["kind"] == st["layers"]["paper"][0]["kind"]:
        return _fail("live/paper mixed")

    g1 = apply_skip_watching_gate(
        db,
        symbol="T8USDT",
        direction="LONG",
        entry_low=10.0,
        entry_high=10.5,
        timeframe="1h",
        now_ts=1_800_000_000.0,
        current_price=10.2,
    )
    if not g1["create"]:
        return _fail("first watching")
    record_skip_if_valid(db, g1, symbol="T8USDT", timeframe="1h")
    g2 = apply_skip_watching_gate(
        db,
        symbol="T8USDT",
        direction="LONG",
        entry_low=10.0,
        entry_high=10.5,
        timeframe="1h",
        now_ts=1_800_000_060.0,
        current_price=10.2,
    )
    if g2["create"]:
        return _fail("dedup same zone")
    g3 = apply_skip_watching_gate(
        db,
        symbol="T8USDT",
        direction="SHORT",
        entry_low=11.0,
        entry_high=11.4,
        timeframe="1h",
        now_ts=1_800_000_060.0,
        current_price=11.2,
    )
    if not g3["create"]:
        return _fail("new independent scenario after skip")

    print("OK: test_t8_lifecycle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
