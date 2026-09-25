#!/usr/bin/env python3
"""T8: рівні/скальп. Дотик ≠ сигнал. PENGU-картка бота не копіюється при ATR/Edge fail."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_external_signal import (  # noqa: E402
    VERDICT_CONDITIONAL,
    ingest_external_signal,
    review_external_signal,
)
from office_level_scalp import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    evaluate_level_book,
    infer_trade_mode,
    parse_bot_card_overlay,
    rr_after_costs,
)
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402

PENGU = """
📌 Сигнал бота · ПРЕМІУМ · СКАЛЬП
🟢 LONG · PENGUUSDT · 5m · #17
💡 ⚡ SCALP
💰 Вхід:  0.010273 (50%)
➕ Добір: 0.010139 (30%)
🛑 SL:    0.00993793 (3.3%)
🎯 TP1:   0.0107756 (+4.9%)
🎯 TP2:   0.011172 (+8.8%)
🎯 TP3:   0.0119484 (+16.3%)
💼 $30 ризику · RR 1:2.7
"""


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl) -> dict:
    return {"open": o, "high": h, "low": l, "close": cl}


def _range_bars(n: int = 16) -> list:
    out = []
    for i in range(n):
        if i % 2 == 0:
            out.append(_c(101.0, 103.0, 100.2, 101.5))
        else:
            out.append(_c(101.5, 102.8, 100.4, 101.0))
    return out


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("ATR frozen")
    if SIGNAL_THRESHOLD != 85 or MIN_RR < 1.5:
        return _fail("edge/rr frozen")
    if COMMISSION != 0.0004 or SLIPPAGE != 0.0005:
        return _fail("costs must match T6/T8")
    if scanner_enter_opens_position("CONFIRMED") is not False:
        return _fail("order")
    if infer_trade_mode("5m", "SCALP") != "scalp":
        return _fail("scalp mode")
    if infer_trade_mode("1h", "") != "intraday":
        return _fail("intraday mode")
    if infer_trade_mode("4h", "SWING") != "swing":
        return _fail("swing mode")

    overlay = parse_bot_card_overlay(PENGU)
    if overlay["symbol"] != "PENGUUSDT" or overlay["direction"] != "LONG":
        return _fail(f"overlay {overlay}")
    if overlay["mode"] != "scalp" or not overlay["entry"] or not overlay["sl"]:
        return _fail(f"pengu parse {overlay}")

    orig = ingest_external_signal(text=PENGU, msg_id=17, received_at="2026-09-25T20:09:00+00:00")
    if orig["symbol"] != "PENGUUSDT" or orig["opens_position"] or orig["mode"] != "scalp":
        return _fail(f"ingest {orig}")
    rev = review_external_signal(
        orig,
        market={
            "price": 0.010273,
            "day_used_pct": 120.7,
            "edge_score": 35,
            "sweep": {},
            "m15_ok": False,
            "structure_sl": 0.00993793,
        },
    )
    if rev.verdict != VERDICT_CONDITIONAL or rev.opens_position:
        return _fail(f"pengu must not copy bot {rev.verdict} {rev.reasons}")
    if "WATCHING" not in rev.lifecycle_hint:
        return _fail("pengu watching")

    tiny = rr_after_costs(entry=100.0, sl=99.85, tp=100.12)
    wide = rr_after_costs(entry=100.0, sl=99.0, tp=102.0)
    if tiny is None or tiny >= MIN_RR:
        return _fail(f"scalp costs must kill tiny RR {tiny}")
    if wide is None or wide < MIN_RR:
        return _fail(f"intraday net RR {wide}")

    bars = _range_bars(16)
    touch = evaluate_level_book(
        symbol="ETHUSDT",
        candles=bars,
        confirm_candles=bars[-3:],
        price=101.2,
        day_used_pct=30,
        edge_score=90,
        mode="intraday",
    )
    if touch.opens_position:
        return _fail("touch order")
    dirs = {s.direction for s in touch.scenarios}
    if dirs != {"LONG", "SHORT"}:
        return _fail(f"need both scenarios {dirs}")
    if any(s.status == "CONFIRMED" for s in touch.scenarios):
        return _fail("touch must not confirm")

    reclaim = bars + [_c(100.4, 101.2, 99.6, 100.8)]
    conf = evaluate_level_book(
        symbol="ETHUSDT",
        candles=reclaim,
        confirm_candles=reclaim[-3:],
        price=100.8,
        day_used_pct=30,
        edge_score=90,
        mode="intraday",
    )
    longs = [s for s in conf.scenarios if s.direction == "LONG"]
    if not longs:
        return _fail("no long sc")
    # Якщо RR до наступного рівня після витрат слабкий — лишаємо WATCHING, не форсимо.
    if longs[0].status == "CONFIRMED" and (longs[0].rr_net is None or longs[0].rr_net < MIN_RR):
        return _fail("confirmed with bad net RR")
    if longs[0].status == "CONFIRMED" and longs[0].opens_position:
        return _fail("level card is not an order")

    atr_block = evaluate_level_book(
        symbol="PENGUUSDT",
        candles=bars,
        price=101.0,
        day_used_pct=120.7,
        edge_score=35,
        mode="scalp",
    )
    if any(s.status == "CONFIRMED" for s in atr_block.scenarios):
        return _fail("ATR 120 scalp must not fire")

    print("OK: test_t8_level_scalp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
