#!/usr/bin/env python3
"""T8: зовнішній сигнал бота + боковик/мультиактив. Без автоордера, пороги 80/90/85."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT, T0_ENTRY_BLOCK_PCT  # noqa: E402
from office_bridge import _fetchall, init_office_db  # noqa: E402
from office_external_signal import (  # noqa: E402
    VERDICT_CONDITIONAL,
    VERDICT_CONFIRMED,
    VERDICT_CORRECTION,
    VERDICT_REJECTED,
    follow_up_external_review,
    format_external_review,
    ingest_external_signal,
    persist_external_original,
    review_external_signal,
)
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import RADAR_SYMBOLS, card_levels  # noqa: E402
from office_range_radar import (  # noqa: E402
    T8_SCAN_UNIVERSE,
    evaluate_range_radar,
    format_range_card,
    scan_universe,
)
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl) -> dict:
    return {"open": o, "high": h, "low": l, "close": cl}


def _range_bars(n: int = 16) -> list:
    out = []
    for i in range(n):
        if i % 2 == 0:
            out.append(_c(101.0, 103.0, 100.0, 101.5))
        else:
            out.append(_c(101.5, 102.8, 100.2, 101.0))
    return out


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or T0_ENTRY_BLOCK_PCT != 90.0:
        return _fail("T0 90")
    if GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("80")
    if SIGNAL_THRESHOLD != 85:
        return _fail("Edge 85")
    if RADAR_SYMBOLS != ("BTCUSDT",):
        return _fail("T6 RADAR_SYMBOLS must stay BTC-only")
    if "XAUUSDT" not in T8_SCAN_UNIVERSE or "ETHUSDT" not in T8_SCAN_UNIVERSE:
        return _fail("universe")
    if scanner_enter_opens_position("ПІДТВЕРДЖЕНО") is not False:
        return _fail("auto order")

    raw = "BTCUSDT LONG\nEntry: 100.00\nSL: 99.00\nTP1: 102.00"
    orig = ingest_external_signal(text=raw, msg_id=34, received_at="2026-01-15T13:00:00+00:00")
    orig2 = dict(orig)
    orig2["entry"] = 1.0
    if orig["entry"] == orig2["entry"]:
        return _fail("original must be a snapshot copy, not alias")
    if orig["symbol"] != "BTCUSDT" or orig["direction"] != "LONG":
        return _fail(f"parse {orig}")
    if orig["opens_position"]:
        return _fail("ingest order")

    db = str(Path(tempfile.mkdtemp()) / "ext.db")
    init_office_db(db)
    before = _fetchall(db, "SELECT COUNT(*) FROM trade_journal")[0][0]
    persist_external_original(db, orig)
    after = _fetchall(db, "SELECT COUNT(*) FROM trade_journal")[0][0]
    ev = _fetchall(db, "SELECT event_type FROM office_events WHERE event_type='EXTERNAL_SIGNAL_RECEIVED'")
    if before != after or not ev:
        return _fail("persist leaked journal or missed event")

    rej = review_external_signal(
        orig,
        market={"htf_bias": "SHORT", "sweep": {}, "m15_ok": False, "price": 100.0},
    )
    if rej.verdict != VERDICT_REJECTED or rej.opens_position:
        return _fail(f"reject {rej.verdict}")

    cond = review_external_signal(
        orig,
        market={
            "htf_bias": "LONG",
            "price": 100.0,
            "day_used_pct": 40.0,
            "edge_score": 90,
            "sweep": {},
            "m15_ok": False,
            "need_session": "london",
            "session": "asia",
            "structure_sl": 99.0,
        },
    )
    if cond.verdict != VERDICT_CONDITIONAL or "WATCHING" not in cond.lifecycle_hint:
        return _fail(f"conditional {cond.verdict} {cond.lifecycle_hint}")

    plan = card_levels(direction="LONG", entry=100.0, structure_sl=99.0, rr=2.0)
    aligned = ingest_external_signal(
        text=(
            f"ETHUSDT LONG Entry: {plan['entry']} SL: {plan['sl']} TP1: {plan['tp']}"
        ),
        msg_id=35,
    )
    ok = review_external_signal(
        aligned,
        market={
            "htf_bias": "LONG",
            "price": 100.0,
            "day_used_pct": 40.0,
            "edge_score": 90,
            "sweep": {"ssl_sweep": True, "sweep_level": 99.0},
            "m15_ok": True,
            "m5_ok": True,
            "structure_sl": 99.0,
            "structure_ok": True,
            "liquidity_ok": True,
            "session": "london",
        },
    )
    if ok.verdict != VERDICT_CONFIRMED or ok.opens_position:
        return _fail(f"confirmed {ok.verdict} {ok.reasons}")
    if "аналітика" not in format_external_review(ok).lower() and "позиці" not in format_external_review(ok).lower():
        if "не команда" not in format_external_review(ok).lower():
            return _fail("confirmed must not be an order")

    drifted = ingest_external_signal(
        text="SOLUSDT LONG Entry: 100.00 SL: 98.00 TP1: 101.10",
        msg_id=36,
    )
    corr = review_external_signal(
        drifted,
        market={
            "htf_bias": "LONG",
            "price": 100.0,
            "day_used_pct": 40.0,
            "edge_score": 90,
            "sweep": {"ssl_sweep": True, "sweep_level": 99.0},
            "m15_ok": True,
            "structure_sl": 99.0,
            "structure_ok": True,
            "liquidity_ok": True,
            "session": "london",
        },
    )
    if corr.verdict != VERDICT_CORRECTION or not corr.office_plan:
        return _fail(f"correction {corr.verdict} {corr.reasons}")
    if corr.original.get("sl") == corr.office_plan.get("sl"):
        return _fail("correction must keep original sl distinct")

    gone = follow_up_external_review(cond, market={"scenario_broken": True})
    if gone.verdict != VERDICT_REJECTED:
        return _fail("follow-up cancel")

    gold = ingest_external_signal(text="XAUUSD SHORT Entry: 2650 SL: 2660 TP1: 2630", msg_id=1)
    if gold["symbol"] != "XAUUSDT":
        return _fail(f"gold {gold['symbol']}")

    bars = _range_bars(16)
    inside = evaluate_range_radar(symbol="ETHUSDT", candles=bars, price=101.2, day_used_pct=30, edge_score=90)
    if inside.status != "RANGE_WATCHING" or inside.opens_position or inside.copies_btc_or_gold:
        return _fail(f"inside {inside}")
    if len(inside.hypotheses) < 2:
        return _fail("both hypotheses")
    txt = format_range_card(inside)
    if "не заходим" in txt.lower():
        return _fail("spam copy")
    again = evaluate_range_radar(
        symbol="ETHUSDT",
        candles=bars,
        price=101.2,
        day_used_pct=30,
        edge_score=90,
        prev_fingerprint=str(inside.extras.get("fingerprint") or ""),
    )
    if again.should_notify:
        return _fail("range spam")

    sweep_bars = bars + [_c(102.0, 103.6, 101.8, 102.4)]
    sweep = evaluate_range_radar(symbol="ETHUSDT", candles=sweep_bars, confirm_candles=sweep_bars[-3:])
    if sweep.event != "SWEEP_HIGH" or sweep.status != "PIERCE_WATCHING" or sweep.card:
        return _fail(f"sweep {sweep.event} {sweep.status} {sweep.card}")

    brk = bars + [_c(103.1, 103.8, 102.9, 103.4), _c(103.3, 104.0, 103.2, 103.7)]
    conf = evaluate_range_radar(
        symbol="ETHUSDT",
        candles=brk,
        confirm_candles=brk[-3:],
        price=103.7,
        day_used_pct=30,
        edge_score=90,
        btc_context={"regime": "TREND_DOWN", "direction": "SHORT"},
    )
    if conf.status != "CONFIRMED" or conf.direction != "LONG" or not conf.card or conf.opens_position:
        return _fail(f"break confirm {conf.status} {conf.direction} {conf.reason}")
    if conf.copies_btc_or_gold:
        return _fail("copied btc")

    uni = scan_universe(
        {
            "BTCUSDT": {"candles": bars, "price": 101.0, "regime": "RANGE"},
            "ETHUSDT": {"candles": brk, "confirm_candles": brk[-3:], "price": 103.7, "day_used_pct": 30, "edge_score": 90},
            "XAUUSDT": {"candles": bars, "price": 2650.0, "regime": "RANGE"},
        }
    )
    by = {r.symbol: r for r in uni}
    if by["ETHUSDT"].copies_btc_or_gold or by["ETHUSDT"].status != "CONFIRMED":
        return _fail("universe eth")
    if by["XAUUSDT"].status != "RANGE_WATCHING":
        return _fail("gold watching")

    print("OK: test_t8_external_range")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
