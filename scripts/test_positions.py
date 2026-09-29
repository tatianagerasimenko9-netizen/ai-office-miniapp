#!/usr/bin/env python3
"""Manual position ledger: maths, state machine, idempotency, fees, exposure, Risk Officer link. Temp SQLite, offline."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

from office_bridge import _fetchall, init_office_db, is_confirmed_position_row  # noqa: E402
import office_positions as P  # noqa: E402
from office_risk_context import existing_risk_usdt  # noqa: E402


def err(fn, *a, **k):
    try:
        fn(*a, **k)
    except P.PositionError as e:
        return e.code
    raise AssertionError("expected PositionError")


db = str(Path(tempfile.mkdtemp()) / "pos.db")
init_office_db(db)

# Fail closed until the explicit migration ran.
assert not P.schema_present(db)
assert err(P.open_position, db, symbol="ETHUSDT", direction="LONG", entry=2600, qty=1, sl=2550) == "schema_missing"
P.migrate_positions(db)
P.migrate_positions(db)  # idempotent
assert P.schema_present(db)

# --- validation
bad = dict(symbol="ETHUSDT", direction="LONG", entry="2600", qty="0.5", sl="2550")
assert err(P.open_position, db, **{**bad, "symbol": "ETH;DROP"}) == "bad_symbol"
assert err(P.open_position, db, **{**bad, "direction": "UP"}) == "bad_direction"
assert err(P.open_position, db, **{**bad, "qty": "0"}) == "bad_обсяг"
assert err(P.open_position, db, **{**bad, "sl": "2650"}) == "geometry"          # LONG stop above entry
assert err(P.open_position, db, **{**bad, "tp1": "2500"}) == "geometry"         # LONG target below entry
assert err(P.open_position, db, **{**bad, "tp1": "2700", "tp2": "2650"}) == "geometry"  # TP2 before TP1
assert err(P.open_position, db, **{**bad, "entry": "abc"}) == "bad_ціна входу"
assert err(P.open_position, db, **{**bad, "opened_at": "2999-01-01T00:00"}) == "bad_opened_at"
assert _fetchall(db, "SELECT COUNT(*) FROM trade_journal", ())[0][0] == 0, "invalid input must write nothing"

# --- open a LONG (comma decimals accepted), explicit fee
p = P.open_position(db, symbol="ethusdt", direction="long", entry="2600,5", qty="2", sl="2550", tp1="2700", tp2="2800",
                    fee_usdt="2.1", scenario_id="ETHUSDT|LONG|2595|2605", note="вручну на Binance", idem_key="k-open")
tid = p["trade_id"]
assert p["status"] == "OPEN" and p["symbol"] == "ETHUSDT" and p["direction"] == "LONG" and p["is_real_position"] is True
assert p["entry"] == 2600.5 and p["remaining_qty"] == 2 and p["initial_risk_usdt"] == 101.0   # (2600.5-2550)*2
assert p["risk_now_usdt"] == 101.0 and p["locked_profit_usdt"] == 0 and p["notional_usdt"] == 5201.0
assert p["fees_usdt"] == 2.1 and p["fees_estimated"] is False and p["source"] == "manual_from_scenario"
assert err(P.open_position, db, **{**bad, "idem_key": "k-open"}) == "duplicate", "double tap must not duplicate"
row = _fetchall(db, "SELECT entry_reason, setup_name, position_qty FROM trade_journal WHERE trade_id=?", (tid,))[0]
assert is_confirmed_position_row(row[0], row[1], tid), "Risk Officer / gate must see it as a confirmed position"

# --- exposure feeds the Risk Officer
assert existing_risk_usdt(db)["value"] == 101.0
assert P.exposure(db)["risk_now_usdt"] == 101.0

# --- partial exit: 50% at 2700
p = P.partial_exit(db, tid, price="2700", qty="1", fee_usdt="1.5", idem_key="k-p1")
assert p["remaining_qty"] == 1 and p["realized_gross_usdt"] == 99.5 and p["fees_usdt"] == 3.6 and p["risk_now_usdt"] == 50.5
assert err(P.partial_exit, db, tid, price="2710", qty="1") == "qty_too_big"      # equals remaining -> use close
assert err(P.partial_exit, db, tid, price="2700", qty="0.5", idem_key="k-p1") == "duplicate"
assert P.get_position(db, tid)["remaining_qty"] == 1, "duplicate must not change state"

# --- move SL to breakeven+ : risk becomes zero, profit locked (directional, not abs)
p = P.move_sl(db, tid, sl="2610", note="в плюс")
assert p["sl"] == 2610 and p["risk_now_usdt"] == 0 and p["locked_profit_usdt"] == 9.5
assert existing_risk_usdt(db)["value"] == 0.0, "locked profit must not count as risk"
assert err(P.move_sl, db, tid, sl="2700") == "geometry"                             # not at/over TP1
p = P.move_tp(db, tid, tp2="2850")
assert p["tp2"] == 2850 and p["tp1"] == 2700
assert err(P.move_tp, db, tid) == "missing_tp"

# --- tracking is informational only
t = P.tracking(p, price=2705.0, price_fresh=True, scenario_status="INVALIDATED")
codes = {f["code"] for f in t["flags"]}
assert "TP1_REACHED_BY_PRICE" in codes and "SCENARIO_INVALIDATED" in codes and t["advisory_only"] is True
assert t["unrealized_usdt"] == 104.5 and abs(t["unrealized_r"] - 104.5 / 101.0) < 1e-6
assert {f["code"] for f in P.tracking(p, price=2600.0, price_fresh=False)["flags"]} == {"NO_FRESH_PRICE"}
assert "PRICE_BEYOND_SL" in {f["code"] for f in P.tracking(p, price=2609.0, price_fresh=True)["flags"]}

# --- close the rest at 2650 with an ESTIMATED fee (0.04% default)
p = P.close_position(db, tid, price="2650", idem_key="k-close", note="закрила вручну")
est = round(2650 * 1 * 0.0004, 8)
assert p["status"] == "CLOSED" and p["remaining_qty"] == 0 and p["exit_price"] == 2650 and p["fees_estimated"] is True
assert p["realized_gross_usdt"] == round(99.5 + 49.5, 8), p["realized_gross_usdt"]
assert abs(p["fees_usdt"] - round(3.6 + est, 8)) < 1e-9
net = 149.0 - (3.6 + est)
assert abs(p["realized_net_usdt"] - round(net, 8)) < 1e-6 and p["outcome"] == "WIN"
assert abs(p["r_realized"] - round(net / 101.0, 8)) < 1e-6
assert err(P.close_position, db, tid, price="2650") == "not_open"
assert err(P.move_sl, db, tid, sl="2600") == "not_open"
kinds = [e["kind"] for e in p["events"]]
assert kinds == ["OPEN", "PARTIAL_EXIT", "MOVE_SL", "MOVE_TP", "CLOSE"], kinds
assert existing_risk_usdt(db)["value"] == 0.0 and P.exposure(db)["status"] == "NONE_RECORDED"

# --- SHORT loss with fees, pre-existing position opened earlier without any Lev scenario
q = P.open_position(db, symbol="SOLUSDT", direction="SHORT", entry=150, qty=10, sl=153, opened_at="2026-09-01T10:00",
                    fee_usdt=0.6)
assert q["source"] == "manual_existing" and q["scenario_id"] is None and q["opened_at"].startswith("2026-09-01T10:00")
assert q["initial_risk_usdt"] == 30.0
lost = P.close_position(db, q["trade_id"], price=153, fee_usdt=0.61)
assert lost["outcome"] == "LOSS" and lost["realized_gross_usdt"] == -30.0 and abs(lost["realized_net_usdt"] + 31.21) < 1e-9
assert abs(lost["r_realized"] + 31.21 / 30.0) < 1e-6

# --- void a wrong entry: leaves risk and stats, keeps history
w = P.open_position(db, symbol="XRPUSDT", direction="LONG", entry=0.5, qty=1000, sl=0.48)
assert existing_risk_usdt(db)["value"] == 20.0
assert err(P.void_position, db, w["trade_id"], reason="") == "missing_reason"
v = P.void_position(db, w["trade_id"], reason="помилково внесла")
assert v["status"] == "VOIDED" and existing_risk_usdt(db)["value"] == 0.0
assert w["trade_id"] not in [x["trade_id"] for x in P.list_positions(db, "all")]
assert [e["kind"] for e in v["events"]] == ["OPEN", "VOID"]

# --- stats: only closed manual trades; small sample hides the win rate
st = P.stats(db)
assert st["n"] == 2 and st["wins"] == 1 and st["losses"] == 1 and st["wr_pct"] is None and "n=2" in st["note"]
assert abs(st["net_usdt"] - round(net - 31.21, 8)) < 1e-6 and st["any_fee_estimated"] is True

# --- signals/simulations are not real trades: other journal rows are not touched or listed
assert err(P.get_position, db, "osig-anything") == "not_found"
print("OK manual positions: validation, fees, partials, SL moves, close, void, idempotency, exposure, tracking")
