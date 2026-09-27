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
    _db,
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

    old_url = os.environ.get("DATABASE_URL")
    old_path = os.environ.get("OFFICE_DB_PATH")
    os.environ["DATABASE_URL"] = "postgresql://u:p@host/ai_office_db"
    os.environ["OFFICE_DB_PATH"] = "/tmp/should-not-win.db"
    if not str(_db()).startswith("postgresql://"):
        return _fail(f"v1 must use DATABASE_URL, got {_db()!r}")
    os.environ.pop("DATABASE_URL", None)
    os.environ["OFFICE_DB_PATH"] = "/tmp/local-office.db"
    if _db() != "/tmp/local-office.db":
        return _fail(f"sqlite fallback {_db()!r}")
    if old_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old_url
    if old_path is None:
        os.environ.pop("OFFICE_DB_PATH", None)
    else:
        os.environ["OFFICE_DB_PATH"] = old_path
    print("OK v1 db = Worker DATABASE_URL")

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

        for i, px in enumerate((84870.5, 84940.2, 84713.0, 84755.0)):
            signal_upsert(
                db,
                signal_id=f"desk-range-BTCUSDT-{i}",
                symbol="BTCUSDT",
                direction="LONG",
                entry_low=px,
                entry_high=px,
                sl=83676.0,
                tp1=px * 1.03,
                tp2=None,
                rr=None,
                status="ACTIVE",
                analysis_note="range",
            )
        signal_upsert(
            db,
            signal_id="junk-btc-tp1",
            symbol="BTCUSDT",
            direction="LONG",
            entry_low=None,
            entry_high=None,
            sl=None,
            tp1=1.0,
            tp2=None,
            rr=None,
            status="HIT_TP2",
            analysis_note="tv",
        )
        # watching без стопа не стає «ключовими рівнями»
        signal_upsert(
            db,
            signal_id="watch-btc-px",
            symbol="BTCUSDT",
            direction="LONG",
            entry_low=84860.8,
            entry_high=84860.8,
            sl=None,
            tp1=None,
            tp2=None,
            rr=None,
            status="WATCHING",
            analysis_note="NEAR",
        )
        hm_hide = home_payload()
        btc_hide = [x for x in (hm_hide.get("active_signals") or []) if str(x.get("symbol")).upper() == "BTCUSDT"]
        if btc_hide:
            return _fail(f"legacy desk-range must be hidden, got {btc_hide}")
        sc_hide = scanner_payload()
        sc_btc = [x for x in (sc_hide.get("candidates") or []) if str(x.get("symbol")).upper() == "BTCUSDT"]
        if sc_btc:
            return _fail(f"scanner must not use desk-range as score, got {sc_btc}")
        signal_upsert(
            db,
            signal_id="desk-conf-BTCUSDT-1",
            symbol="BTCUSDT",
            direction="LONG",
            entry_low=84100.0,
            entry_high=84300.0,
            sl=83676.0,
            tp1=86200.0,
            tp2=None,
            rr=2.1,
            status="ACTIVE",
            analysis_note="ckey=BTCUSDT|LONG|84100|84300 confluence",
        )
        hm2 = home_payload()
        if hm2.get("opens_position") is not False:
            return _fail("home must not open position")
        if "не /position" not in str(hm2.get("card_note") or ""):
            return _fail(f"card_note {hm2.get('card_note')}")
        btc = [x for x in (hm2.get("active_signals") or []) if str(x.get("symbol")).upper() == "BTCUSDT"]
        if len(btc) != 1:
            return _fail(f"BTC confluence must be 1, got {btc}")
        if "desk-range" in str(btc[0].get("signal_id") or ""):
            return _fail(f"legacy id leaked {btc[0]}")
        lv = (hm2.get("levels") or {}).get("levels") or {}
        if lv.get("sl") is None or lv.get("tp1") in (None, 1, 1.0):
            return _fail(f"btc key levels {hm2.get('levels')}")
        if abs(float(lv.get("entry_low") or 0) - 84860.8) < 1e-6:
            return _fail("watching price must not be key levels")
        if abs(float(lv.get("entry_low") or 0) - 84870.5) < 1e-6:
            return _fail("desk-range chase must not be key levels")
        sigs = signals_payload()
        btc_s = [x for x in (sigs.get("cards") or []) if str(x.get("symbol")).upper() == "BTCUSDT"]
        if len(btc_s) != 1:
            return _fail(f"signals tab dupes {btc_s}")
        print("OK desk-range hidden, confluence BTC=1, junk hidden")
        return 0
    finally:
        try:
            os.unlink(db)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
