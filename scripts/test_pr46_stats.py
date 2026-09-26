#!/usr/bin/env python3
"""PR46: /stats журналу сигналів — мало даних / WR / свіп→TP / RSI 85/92."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bridge import (  # noqa: E402
    OFFICE_SIGNAL_REASON,
    OFFICE_SIGNAL_SETUP,
    init_office_db,
    journal_close_trade,
    journal_open_office_signal,
    journal_open_trade,
    journal_update_excursions,
)
from office_signal_stats import MIN_GROUP, build_stats_report, classify_setup, kyiv_session  # noqa: E402
from office_telegram_policy import EVENT_SIGNAL_ENTRY, may_send_proactive  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if classify_setup("PUMP hunter", {"setup": "PUMP"}) != "PUMP":
        return _fail("classify PUMP")
    if classify_setup("SWEEP_REENTRY") != "REENTRY":
        return _fail("classify REENTRY")
    if classify_setup("SC-OTE hunter") != "SC-OTE":
        return _fail("classify SC-OTE")
    if kyiv_session("2026-09-26T06:00:00+03:00") != "ASIA":
        return _fail("asia session")
    if not may_send_proactive(EVENT_SIGNAL_ENTRY):
        return _fail("quiet policy")

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_office_db(db)
        empty = build_stats_report(db)
        if "DATA_UNAVAILABLE" not in str(empty.get("message")):
            return _fail(f"empty journal: {empty}")
        print("OK empty DATA_UNAVAILABLE")

        journal_open_trade(
            db,
            trade_id="pos-BTCUSDT-1",
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=100,
            stop_loss=95,
            setup_name="T1_MY_POSITION",
            entry_reason="t1 /position confirm",
        )
        mixed = build_stats_report(db)
        if mixed.get("n"):
            return _fail("/position must not enter /stats")
        print("OK /position excluded")

        for i in range(5):
            tid = journal_open_office_signal(
                db,
                signal_id=f"thin-{i}",
                symbol="SOLUSDT",
                direction="LONG",
                entry_price=100,
                stop_loss=97,
                take_profit=106,
                timeframe="H1",
                setup_note="SC-OTE",
            )
            journal_close_trade(db, trade_id=tid, outcome="WIN", exit_price=106, pnl_pct=6.0)
        thin = build_stats_report(db)
        if "мало даних" not in str(thin.get("message")):
            return _fail(f"need thin group: {thin.get('message')}")
        print("OK n<20 → мало даних")

        for i in range(MIN_GROUP):
            extra = {
                "mfe_pct": 4.0,
                "mae_pct": 3.2 if i < 6 else 0.4,
                "rsi_at_signal": 70.0 if i < 4 else 86.0,
                "rsi_peak": 93.0 if i < 4 else 80.0,
                "sweep_then_tp": i < 6,
                "session": "ASIA" if i % 2 == 0 else "LONDON",
            }
            tid = journal_open_office_signal(
                db,
                signal_id=f"fat-{i}",
                symbol="ETHUSDT",
                direction="LONG" if i % 3 else "SHORT",
                entry_price=100,
                stop_loss=97,
                take_profit=106,
                timeframe="H1" if i % 2 else "M15",
                setup_note="PUMP" if i % 2 else "SC-OTE",
                extra=extra,
            )
            journal_update_excursions(db, trade_id=tid, mfe_pct=extra["mfe_pct"], mae_pct=extra["mae_pct"], extra=extra)
            journal_close_trade(
                db,
                trade_id=tid,
                outcome="WIN" if i % 2 else "LOSS",
                exit_price=106 if i % 2 else 97,
                pnl_pct=6.0 if i % 2 else -3.0,
            )
        fat = build_stats_report(db)
        msg = str(fat.get("message") or "")
        if "WR" not in msg:
            return _fail(msg)
        if "Свіп стопа, потім TP" not in msg:
            return _fail("missing sweep calibration")
        if "RSI вхід" not in msg:
            return _fail("missing RSI line")
        if "PUMP:" not in msg or "SC-OTE:" not in msg:
            return _fail("missing setup buckets")
        print(msg)
        print("OK fat journal stats")
        return 0
    finally:
        try:
            os.unlink(db)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
