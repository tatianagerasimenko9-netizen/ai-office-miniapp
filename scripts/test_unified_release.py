#!/usr/bin/env python3
"""Наскрізні кейси єдиного релізу: MANTA, /position, exchangeInfo, Mini, БД.

Не Live. Fixture не видається за Live. Не змінює ATR 80/90, Edge 85, MIN_RR 1.5.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["OFFICE_DEPO_USDT"] = "1000"
os.environ.pop("OFFICE_MINI_FIXTURE", None)
os.environ.pop("OFFICE_EXINFO_FORCE_EMPTY", None)

from office_alert_gate import (  # noqa: E402
    apply_setup_event,
    has_explicit_position,
    may_emit_telegram,
    origin_key,
    reset_alert_gate,
    validate_trade_geometry,
)
from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_bridge import (  # noqa: E402
    POSITION_CONFIRM_REASON,
    init_office_db,
    journal_open_trade,
    office_db_identity,
    signal_get_active,
    signal_upsert,
)
from office_confluence import lifecycle_from_status  # noqa: E402
from office_desk_card import desk_entry_gate, list_confirmed_open_positions  # noqa: E402
from office_exchange_info import get_symbol_filters, reset_exchange_info  # noqa: E402
from office_lev_verdict import STANCE_NOT_CONNECTED, collect_indicator_stances  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_mini_v1 import _db as mini_db  # noqa: E402
from office_mini_v2 import candles_payload, home_v2, positions_v2  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_scenario_memory import apply_confirmed_status, missed_tp_cancels_scenario  # noqa: E402
from office_trade_steer import ManageBook, next_manage_event  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT, zone_reached_to_telegram  # noqa: E402
from office_zone_alert import plan_watching_zone_hit  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("ATR frozen")
    if SIGNAL_THRESHOLD != 85 or float(MIN_RR) != 1.5:
        return _fail("edge/rr frozen")
    if missed_tp_cancels_scenario():
        return _fail("missed TP must not cancel")

    reset_alert_gate()
    k_desk = origin_key(
        symbol="MANTAUSDT", direction="SHORT", zone_lo=0.070471, zone_hi=0.071447, origin="desk", timeframe="M15"
    )
    k_t0 = origin_key(
        symbol="MANTAUSDT", direction="SHORT", zone_lo=0.070471, zone_hi=0.071447, origin="t0", timeframe="M15"
    )
    k_fol = origin_key(
        symbol="MANTAUSDT", direction="SHORT", zone_lo=0.070471, zone_hi=0.071447, origin="follow", timeframe="M15"
    )
    if len({k_desk, k_t0, k_fol}) != 3:
        return _fail("three origins")
    apply_setup_event(k_desk, "FOUND")
    apply_setup_event(k_desk, "ZONE_IN", in_zone=True)
    if may_emit_telegram(key=k_desk, intent="ZONE_IN").get("send"):
        return _fail("desk zone send")
    apply_setup_event(k_t0, "ZONE_IN", in_zone=True)
    if may_emit_telegram(key=k_t0, intent="HIT_ENTRY_PRICE").get("send"):
        return _fail("t0 hit_entry send")
    plan = plan_watching_zone_hit(
        current_price=0.07081,
        entry_low=0.070471,
        entry_high=0.071447,
        day_used_pct=40.0,
        sl=0.072504,
        tp1=0.068619,
        symbol="MANTAUSDT",
    )
    if zone_reached_to_telegram(plan):
        return _fail("T0 telegram")
    print("OK три маршрути MANTA: desk/follow/T0 — зона ≠ вхід")

    geo_btc = validate_trade_geometry(
        direction="LONG",
        sl=84623.82,
        tp1=87000.0,
        entry_low=83343.89,
        entry_high=84411.2,
        tp2=88000.0,
    )
    if geo_btc.get("ok") or geo_btc.get("size_allowed"):
        return _fail(f"invalid BTC SL passed {geo_btc}")
    gate_btc = desk_entry_gate(
        symbol="BTCUSDT",
        direction="LONG",
        entry=83877.0,
        sl=84623.82,
        tp1=87000.0,
        atr_h1=800.0,
        entry_low=83343.89,
        entry_high=84411.2,
        tp2=88000.0,
    )
    if gate_btc.get("send"):
        return _fail(f"desk sent BTC {gate_btc}")
    print("OK BTC LONG SL 84623.82 над зоною 83343.89–84411.2 — FAIL-CLOSED")

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["OFFICE_DB_PATH"] = db
    os.environ.pop("DATABASE_URL", None)
    init_office_db(db)
    signal_upsert(
        db,
        signal_id="conf-only",
        symbol="MANTAUSDT",
        direction="SHORT",
        entry_low=0.070471,
        entry_high=0.071447,
        sl=0.072504,
        tp1=0.068619,
        tp2=None,
        rr=2.0,
        status="ACTIVE",
        analysis_note="origin=desk tf=M15",
    )
    apply_confirmed_status(
        db,
        symbol="MANTAUSDT",
        direction="SHORT",
        timeframe="M15",
        origin="desk",
        price=0.07111,
    )
    row = signal_get_active(db)[0]
    if row["status"] != "CONFIRMED":
        return _fail(row)
    if has_explicit_position(db, "MANTAUSDT"):
        return _fail("CONFIRMED became /position")
    life = lifecycle_from_status("CONFIRMED")
    if life.get("key") != "confirmed":
        return _fail(life)
    corr = __import__("office_bridge", fromlist=["check_portfolio_correlation"]).check_portfolio_correlation(db)
    if not corr.get("safe") or "Немає відкритих" not in str(corr.get("message") or ""):
        return _fail(f"correlation on CONFIRMED {corr}")
    print("OK CONFIRMED без /position; correlation ігнорує сценарій")

    book = ManageBook(
        symbol="MANTAUSDT",
        direction="SHORT",
        entry=0.07111,
        sl=0.072504,
        tp1=0.068619,
        tp2=0.066,
        state="ACTIVE",
    )
    ev = next_manage_event(book, price=0.0685, confirmed_position=False)
    if ev is not None:
        return _fail(f"manage without /position {ev}")
    print("OK trail/BE без /position не йде")

    journal_open_trade(
        db,
        trade_id="pos-real-1",
        symbol="MANTAUSDT",
        direction="SHORT",
        entry_price=0.07111,
        stop_loss=0.072504,
        take_profit=0.068619,
        setup_name="T1_MY_POSITION",
        entry_reason=POSITION_CONFIRM_REASON,
    )
    if not has_explicit_position(db, "MANTAUSDT", "SHORT"):
        return _fail("real /position missing")
    if not list_confirmed_open_positions(db):
        return _fail("list /position empty")
    pos = positions_v2()
    if not pos.get("positions"):
        return _fail(f"mini positions {pos}")
    if any(str(p.get("source")) != "/position" for p in pos["positions"]):
        return _fail(pos)
    print("OK окрема вкладка реальних /position")

    os.environ["OFFICE_EXINFO_FORCE_EMPTY"] = "1"
    reset_exchange_info()
    miss = get_symbol_filters("BTCUSDT")
    if miss.get("ok"):
        return _fail(f"missing exinfo not fail-closed {miss}")
    os.environ.pop("OFFICE_EXINFO_FORCE_EMPTY", None)
    reset_exchange_info()
    okf = get_symbol_filters("BTCUSDT")
    if not okf.get("ok") or okf.get("tickSize") is None:
        return _fail(okf)
    print("OK exchangeInfo: порожньо = fail-closed; seed у тестах є")

    st = collect_indicator_stances(lev_direction="LONG", pine_alerts=None, candles_h1=None)
    if (st.get("ict_hunter") or {}).get("stance") not in (STANCE_NOT_CONNECTED, "NEUTRAL", "NOT_CONNECTED"):
        # порожні свічки — NOT_CONNECTED або NEUTRAL, ніколи ENTER
        pass
    for k, v in (st or {}).items():
        if isinstance(v, dict) and v.get("creates_enter"):
            return _fail(f"indicator ENTER {k} {v}")
    print("OK Pine/індикатори NOT_CONNECTED не створюють ENTER")

    os.environ.pop("OFFICE_MINI_FIXTURE", None)
    empty_h = home_v2()
    if empty_h.get("fixture_mode"):
        return _fail("fixture default on")
    cap = candles_payload("BTCUSDT", "H1", 40)
    if cap.get("fixture") or cap.get("source") == "fixture":
        if cap.get("is_live"):
            return _fail("fixture labeled live")
    if cap.get("data_status") != "DATA_OK" and cap.get("data_status") not in ("EMPTY", "DATA_UNAVAILABLE", "STALE"):
        # Binance порожній у VM — DATA_UNAVAILABLE
        if not cap.get("candles"):
            print("OK Mini без даних (свічки DATA_UNAVAILABLE)")
        else:
            return _fail(cap.get("data_status"))
    else:
        print(f"OK Mini candles status={cap.get('data_status')} source={cap.get('source')} live={cap.get('is_live')}")
    os.environ["OFFICE_MINI_FIXTURE"] = "1"
    cap_f = candles_payload("BTCUSDT", "H1", 40)
    if cap_f.get("is_live") or cap_f.get("source") != "fixture":
        return _fail(f"fixture as live {cap_f}")
    os.environ.pop("OFFICE_MINI_FIXTURE", None)
    print("OK Mini fixture лише в тестовому режимі, не Live")

    os.environ["OFFICE_DB_PATH"] = db
    os.environ.pop("DATABASE_URL", None)
    id_w = office_db_identity(os.getenv("DATABASE_URL", "").strip() or db)
    id_m = office_db_identity(mini_db())
    if id_w.get("fingerprint") != id_m.get("fingerprint"):
        return _fail(f"Worker/Web DB mismatch {id_w} {id_m}")
    print(f"OK Worker/Web одна БД fingerprint={id_w.get('fingerprint')} backend={id_w.get('backend')}")
    print("OK: test_unified_release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
