#!/usr/bin/env python3
"""Paper шар і desk_state: не змішує live / paper / watching."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_desk_state import build_desk_state  # noqa: E402
from office_paper_trading import run_session_paper  # noqa: E402
from office_session_radar import KIND_LIVE, KIND_PAPER, KIND_WATCHING  # noqa: E402
from office_t6_backtest import load_ohlcv_file  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0:
        return _fail("T0 90")
    ctrl = ROOT / "fixtures" / "t6_backtest_control.json"
    load_ohlcv_file(ctrl)
    paper = run_session_paper(str(ctrl))
    if paper.kind != KIND_PAPER or paper.opens_live_journal:
        return _fail("paper kind")
    if "не жива" not in paper.disclaimer.lower() and "не запис" not in paper.disclaimer.lower():
        return _fail("disclaimer")
    st = build_desk_state(
        "unused.db",
        watching_rows=[
            {
                "signal_id": "watch-x",
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "entry_low": 82963,
                "entry_high": 83434,
                "analysis_note": "ok",
            }
        ],
        journal_rows=[
            {"trade_id": "pos-1", "symbol": "BTCUSDT", "direction": "LONG", "status": "OPEN", "entry_reason": "explicit /position by owner"},
            {"trade_id": "desk-enter-1", "symbol": "ETHUSDT", "direction": "LONG", "status": "OPEN", "setup_name": "DESK_ENTER"},
        ],
        force_order_events=[{"ts_utc": "t", "payload_json": {"connected": True, "events_in_window": 0, "creates_enter": False}}],
        paper_trades=[{"symbol": "BTCUSDT", "outcome": "n/a"}],
    )
    if st["counts"]["watching"] != 1 or st["layers"]["watching"][0]["kind"] != KIND_WATCHING:
        return _fail("watching layer")
    if st["counts"]["live_positions"] != 1 or st["layers"]["positions_live"][0]["kind"] != KIND_LIVE:
        return _fail("live vs desk enter")
    if st["counts"]["signals"] != 1:
        return _fail("desk enter is signal not live")
    if st["layers"]["paper"][0]["kind"] != KIND_PAPER:
        return _fail("paper kind")
    if st["atr_policy"]["t0_entry_block_pct"] != 90.0:
        return _fail("desk atr")
    print("OK: test_paper_desk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
