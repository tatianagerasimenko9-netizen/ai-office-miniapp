#!/usr/bin/env python3
"""Етап після #63: desk-range hide, hydrate, scan facts, картка R, archive dry-run."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bridge import init_office_db, journal_open_office_signal, signal_upsert  # noqa: E402
from office_confluence import hydrate_live_from_db, live_items, reset_live  # noqa: E402
from office_desk_card import (  # noqa: E402
    card_has_banned,
    format_desk_card,
    is_legacy_desk_range,
    latest_open_desk_signal,
)
from office_market_state import record_scan_facts  # noqa: E402
from office_mini_v1 import live_unique_cards, scanner_payload  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from plan_archive_desk_range import SNAPSHOT_OPEN_OSIG, plan_dict  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or SIGNAL_THRESHOLD != 85 or float(MIN_RR) != 1.5:
        return _fail("frozen gates")
    if not is_legacy_desk_range("osig-desk-range-BTCUSDT-1"):
        return _fail("legacy osig")
    if not is_legacy_desk_range({"signal_id": "desk-range-BTCUSDT-2", "analysis_note": "x"}):
        return _fail("legacy dict")
    if is_legacy_desk_range("desk-conf-BTCUSDT-1"):
        return _fail("conf must not be legacy")
    if is_legacy_desk_range("desk-боковик-ETHUSDT-1"):
        return _fail("new range-alert id is not desk-range-")

    txt = format_desk_card(
        symbol="BTCUSDT",
        direction="LONG",
        timeframe="H1",
        entry=84150,
        sl=83676,
        tp1=86200,
        entry_low=84100,
        entry_high=84300,
        setup_type="SC-OTE",
        grade="A",
        zone_line="OB + свіп",
        now_line="Зараз: поза угодою, чекаю відкат",
    )
    banned = card_has_banned(txt)
    if banned:
        return _fail(f"banned {banned} in {txt}")
    if "RR 1:" in txt:
        return _fail(txt)
    if "до TP1" not in txt or "R" not in txt:
        return _fail(f"need R line {txt}")
    if "None" in txt:
        return _fail(txt)
    print("OK card R-line")

    plan = plan_dict()
    if plan.get("apply") is not False:
        return _fail("plan must not apply")
    if len(plan.get("snapshot_ids") or []) != 6:
        return _fail("snapshot 6")
    if SNAPSHOT_OPEN_OSIG[0] != "osig-desk-range-BTCUSDT-1790505544":
        return _fail("btc newest snapshot")
    print("OK archive dry-run plan")

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old = os.environ.get("OFFICE_DB_PATH")
    os.environ["OFFICE_DB_PATH"] = db
    try:
        init_office_db(db)
        signal_upsert(
            db,
            signal_id="desk-range-BTCUSDT-9",
            symbol="BTCUSDT",
            direction="LONG",
            entry_low=84870.5,
            entry_high=84870.5,
            sl=83676.0,
            tp1=87309.0,
            tp2=None,
            rr=None,
            status="ACTIVE",
            analysis_note="range chase",
        )
        journal_open_office_signal(
            db,
            signal_id="desk-range-BTCUSDT-9",
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=84870.5,
            stop_loss=83676.0,
            take_profit=87309.0,
            setup_note="range",
        )
        signal_upsert(
            db,
            signal_id="desk-conf-ETHUSDT-1",
            symbol="ETHUSDT",
            direction="SHORT",
            entry_low=3900,
            entry_high=3920,
            sl=3980,
            tp1=3780,
            tp2=None,
            rr=None,
            status="ACTIVE",
            analysis_note="ckey=ETHUSDT|SHORT|3900|3920",
        )
        if latest_open_desk_signal(db, "BTCUSDT"):
            return _fail("legacy must not block symbol")
        cards = live_unique_cards(
            [
                {
                    "signal_id": "desk-range-BTCUSDT-9",
                    "symbol": "BTCUSDT",
                    "direction": "LONG",
                    "entry_low": 84870.5,
                    "entry_high": 84870.5,
                    "sl": 83676,
                    "tp1": 87309,
                    "status": "ACTIVE",
                },
                {
                    "signal_id": "desk-conf-ETHUSDT-1",
                    "symbol": "ETHUSDT",
                    "direction": "SHORT",
                    "entry_low": 3900,
                    "entry_high": 3920,
                    "sl": 3980,
                    "tp1": 3780,
                    "status": "ACTIVE",
                },
            ]
        )
        if len(cards) != 1 or cards[0]["symbol"] != "ETHUSDT":
            return _fail(f"cards {cards}")
        reset_live()
        n = hydrate_live_from_db(db)
        keys = [k for k, _ in live_items()]
        if n != 1:
            return _fail(f"hydrate n={n} keys={keys}")
        if any("84870" in k or "BTCUSDT|LONG" in k for k in keys) and not any("ETHUSDT" in k for k in keys):
            return _fail(f"hydrated legacy {keys}")
        if not any("ETHUSDT" in k for k in keys):
            return _fail(f"need eth key {keys}")

        empty_sc = scanner_payload()
        if empty_sc.get("data_status") != "DATA_UNAVAILABLE":
            return _fail(f"scanner without facts {empty_sc}")
        rec = record_scan_facts(db, "SOLUSDT", rsi_h1=55.0, data_quality="OK")
        if not rec or (rec.get("signal") or {}).get("rsi") != 55.0:
            return _fail(f"scan facts {rec}")
        if (rec.get("signal") or {}).get("score") not in (None,):
            return _fail("must not invent score")
        sc = scanner_payload()
        if sc.get("data_status") != "DATA_OK":
            return _fail(str(sc))
        row = (sc.get("candidates") or [None])[0]
        if not row or row.get("symbol") != "SOLUSDT" or row.get("rsi") != 55.0:
            return _fail(str(sc))
        if row.get("score") not in (None,):
            return _fail("scanner invented score")
        print("OK hydrate/hide/scanner facts")
        return 0
    finally:
        if old is None:
            os.environ.pop("OFFICE_DB_PATH", None)
        else:
            os.environ["OFFICE_DB_PATH"] = old
        try:
            os.unlink(db)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
