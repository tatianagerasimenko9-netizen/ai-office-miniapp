#!/usr/bin/env python3
"""Risk Officer in Lev's live cycle: shadow by default, veto only with flag.

Temporary SQLite, no network, Telegram or orders.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

from office_bridge import POSITION_CONFIRM_REASON, _fetchall, init_office_db, journal_open_trade  # noqa: E402
from office_lev_verdict import finalize_lev  # noqa: E402
from office_risk_context import apply_risk_officer, build_risk_context, existing_risk_usdt  # noqa: E402

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
FRESH = [{"ts": (NOW - timedelta(minutes=5)).isoformat(), "close": 100.0}]
STALE = [{"ts": (NOW - timedelta(hours=3)).isoformat(), "close": 100.0}]
DRAFT = {
    "symbol": "SOLUSDT", "direction": "LONG", "send_card": True,
    "entry": 100.0, "sl": 98.0, "tp1": 104.0, "rr": 2.0,
    "invalidation": 98.0, "confluence": {"tags": ["H1"], "n": 3},
    "atr": {}, "liquidity": {}, "reason": "confirmed HTF structure",
}


def events(db):
    return [(r[0], json.loads(r[1])) for r in _fetchall(db, "SELECT event_type, payload_json FROM office_events ORDER BY id", ())]


def main():
    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_depo = os.environ.get("OFFICE_DEPO_USDT")
    os.environ["OFFICE_DEPO_USDT"] = "1000"
    os.environ.pop("OFFICE_RISK_OFFICER_ENFORCE", None)
    try:
        init_office_db(db)
        cycle = finalize_lev(DRAFT)
        assert cycle["send"]

        # No open positions: existing risk is a verified 0; quantity from depo 1%.
        ex = existing_risk_usdt(db)
        assert ex["status"] == "OK" and ex["value"] == 0.0
        ctx = build_risk_context(db_path=db, symbol="SOLUSDT", direction="LONG", entry=100, sl=98,
                                 candles_ltf=FRESH, market_context={"data_status": "DATA_OK"}, now_utc=NOW)
        assert ctx["equity_source"] == "config:OFFICE_DEPO_USDT"
        assert abs(ctx["quantity"] - 5.0) < 1e-9, ctx  # 10 USDT risk / 2 USDT per coin
        assert ctx["data_quality"] == "OK" and ctx["context_quality"] == "OK"
        assert ctx["execution_quality"] == "UNAVAILABLE"

        # Shadow (default): decision unchanged, review journaled as would-veto.
        out = apply_risk_officer(cycle, db_path=db, symbol="SOLUSDT", candles_ltf=FRESH,
                                 market_context={"data_status": "DATA_OK"}, now_utc=NOW)
        assert out["send"] and out["action"] == "SEND" and out["risk_mode"] == "shadow"
        assert out["risk_review"]["order_authorized"] is False
        ev = events(db)
        assert ev[-1][0] == "RISK_SHADOW_REVIEW" and ev[-1][1]["would_veto"] is True
        assert not out["scenario_id"], out["scenario_id"]
        # The same plan on the next radar pass is not journaled again.
        n0 = len(ev)
        apply_risk_officer(cycle, db_path=db, symbol="SOLUSDT", candles_ltf=FRESH,
                           market_context={"data_status": "DATA_OK"}, now_utc=NOW)
        assert len(events(db)) == n0, "duplicate shadow review written"
        # Linked to the scenario id from the draft's setup key.
        keyed = finalize_lev({**DRAFT, "confluence": {"tags": ["H1"], "n": 3, "setup_key": "SOLUSDT|LONG|99|101"}})
        k = apply_risk_officer(keyed, db_path=db, symbol="SOLUSDT", candles_ltf=FRESH,
                               market_context={"data_status": "DATA_OK"}, now_utc=NOW)
        assert k["scenario_id"] == "SOLUSDT|LONG|99|101"
        row = _fetchall(db, "SELECT signal_id FROM office_events ORDER BY id DESC LIMIT 1", ())[0]
        assert row[0] == "SOLUSDT|LONG|99|101", row
        assert "EXECUTION_NOT_VERIFIED" in ev[-1][1]["reasons"]

        # Stale LTF data is reported, never treated as OK.
        stale = build_risk_context(db_path=db, symbol="SOLUSDT", direction="LONG", entry=100, sl=98,
                                   candles_ltf=STALE, market_context={"data_status": "DATA_OK"}, now_utc=NOW)
        assert stale["data_quality"] == "UNAVAILABLE" and "STALE_SNAPSHOT" in stale["data_reasons"]
        assert build_risk_context(db_path=db, symbol="SOLUSDT", direction="LONG", entry=100, sl=98,
                                  candles_ltf=None, market_context=None, now_utc=NOW)["context_quality"] == "UNAVAILABLE"

        # Enforce: same finalize_lev veto → WAIT, journaled as RISK_VETO.
        enf = apply_risk_officer(cycle, db_path=db, symbol="SOLUSDT", candles_ltf=FRESH,
                                 market_context={"data_status": "DATA_OK"}, enforce=True, now_utc=NOW)
        assert enf["action"] == "WAIT" and not enf["send"] and enf["risk_mode"] == "enforce"
        assert events(db)[-1][0] == "RISK_VETO"

        # Non-SEND decisions are never reviewed or promoted.
        wait = {**cycle, "action": "WAIT", "send": False}
        n = len(events(db))
        assert apply_risk_officer(wait, db_path=db, symbol="SOLUSDT", enforce=True) is wait
        assert len(events(db)) == n

        # Open confirmed /position without qty → existing risk unknown, not zero.
        journal_open_trade(db, trade_id="pos-eth-1", symbol="ETHUSDT", direction="LONG", entry_price=2600,
                           stop_loss=2550, take_profit=2700, position_qty=0.1,
                           entry_reason=POSITION_CONFIRM_REASON)
        ex1 = existing_risk_usdt(db)
        assert ex1["status"] == "OK" and abs(ex1["value"] - 5.0) < 1e-9 and ex1["open"] == 1, ex1
        journal_open_trade(db, trade_id="pos-eth-2", symbol="ETHUSDT", direction="LONG", entry_price=2600,
                           stop_loss=2550, take_profit=2700, entry_reason=POSITION_CONFIRM_REASON)
        ex2 = existing_risk_usdt(db)
        assert ex2["value"] is None and ex2["status"] == "UNAVAILABLE" and "pos-eth-2" in ex2["reason"], ex2
        r = apply_risk_officer(cycle, db_path=db, symbol="SOLUSDT", candles_ltf=FRESH,
                               market_context={"data_status": "DATA_OK"}, now_utc=NOW, log=False)
        assert "INVALID_EXISTING_RISK" in r["risk_review"]["reasons"]

        # Without depo there is no quantity and no approval.
        os.environ.pop("OFFICE_DEPO_USDT", None)
        r = apply_risk_officer(cycle, db_path=db, symbol="SOLUSDT", candles_ltf=FRESH,
                               market_context={"data_status": "DATA_OK"}, now_utc=NOW, log=False)
        assert "INCOMPLETE_PLAN" in r["risk_review"]["reasons"] and r["send"]
    finally:
        if old_depo is None:
            os.environ.pop("OFFICE_DEPO_USDT", None)
        else:
            os.environ["OFFICE_DEPO_USDT"] = old_depo
        os.unlink(db)
    print("OK Risk Officer in Lev cycle: shadow journal, enforce veto, unknown risk stays unknown, no orders")


if __name__ == "__main__":
    main()
