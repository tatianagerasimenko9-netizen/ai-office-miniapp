#!/usr/bin/env python3
"""PR47: Mini App v1 read-only — головна/сигнали/сканер/позиції/stats."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bridge import init_office_db, journal_open_trade, signal_upsert  # noqa: E402
from office_market_state import market_state_upsert  # noqa: E402
from office_mini_v1 import (  # noqa: E402
    html_v1,
    home_payload,
    positions_payload,
    scanner_payload,
    signals_payload,
    stats_payload,
)


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    html = html_v1().lower()
    for banned in ("buy now", "place order", "market buy", "limit buy", "відкрити ордер"):
        if banned in html:
            return _fail(f"order button leaked: {banned}")
    if "readonly" not in html and "лише читання" not in html:
        return _fail("need read-only banner")
    print("OK html read-only")

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["OFFICE_DB_PATH"] = db
    try:
        init_office_db(db)
        empty_s = signals_payload()
        if empty_s.get("data_status") != "DATA_UNAVAILABLE":
            return _fail(f"empty signals {empty_s}")
        empty_p = positions_payload()
        if empty_p.get("data_status") != "DATA_UNAVAILABLE":
            return _fail(f"empty pos {empty_p}")
        print("OK empty DATA_UNAVAILABLE")

        signal_upsert(
            db,
            signal_id="s1",
            symbol="SOLUSDT",
            direction="LONG",
            entry_low=100.0,
            entry_high=101.0,
            sl=97.0,
            tp1=106.0,
            tp2=110.0,
            rr=2.0,
            status="ACTIVE",
            analysis_note="SC-OTE",
        )
        market_state_upsert(
            db,
            "SOLUSDT",
            regime="trend",
            signal={"score": 12, "rsi": 61, "pump_score": 11, "dump_score": 2},
            office_decision="WATCH",
        )
        journal_open_trade(
            db,
            trade_id="pos-ETHUSDT-x",
            symbol="ETHUSDT",
            direction="LONG",
            entry_price=3000,
            stop_loss=2900,
            setup_name="T1_MY_POSITION",
            entry_reason="explicit /position by owner",
        )
        sig = signals_payload()
        if not sig.get("cards") or sig["cards"][0]["symbol"] != "SOLUSDT":
            return _fail(str(sig))
        if sig["cards"][0]["status"] != "активний":
            return _fail(f"status ua {sig['cards'][0]}")
        sc = scanner_payload()
        if not sc.get("candidates") or sc["candidates"][0]["symbol"] != "SOLUSDT":
            return _fail(str(sc))
        if sc.get("alerts") is not False:
            return _fail("scanner must not alert")
        pos = positions_payload()
        if len(pos.get("positions") or []) != 1:
            return _fail(f"position mix {pos}")
        st = stats_payload()
        if "DATA_UNAVAILABLE" not in str(st.get("message")) and not st.get("n", 1) >= 0:
            return _fail(str(st))
        hm = home_payload()
        if hm.get("orders") is not False:
            return _fail("home must declare no orders")
        if not hm.get("active_signals"):
            return _fail(f"home active {hm}")
        print("OK payloads")
        return 0
    finally:
        try:
            os.unlink(db)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
