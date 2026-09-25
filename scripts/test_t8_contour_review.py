#!/usr/bin/env python3
"""PENGU #17 повторний розбір 23:53: свіжість, ATR як правило, без вигаданої зони."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_external_signal import (  # noqa: E402
    ingest_external_signal,
    review_external_signal,
)
from office_level_scalp import parse_bot_card_clock  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_skip_plan import case_key  # noqa: E402
from office_telegram_filter import alert_decision, level_book_to_alert  # noqa: E402
from office_trader_plan import compose_trader_plan, format_trader_plan  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402

PENGU = """
📌 Сигнал бота · ПРЕМІУМ · СКАЛЬП
🟢 LONG · PENGUUSDT · 5m · #17
🕐 23:09 25.09.2026 · поза іменованою сесією · TREND
💰 Вхід:  0.010273 (50%)
➕ Добір: 0.010139 (30%)
🛑 SL:    0.00993793 (3.3%)
🎯 TP1:   0.0107756 (+4.9%)
🎯 TP2:   0.011172 (+8.8%)
"""


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or SIGNAL_THRESHOLD != 85:
        return _fail("thresholds")
    if scanner_enter_opens_position("ПРОПУСК") is not False:
        return _fail("order")
    clock = parse_bot_card_clock(PENGU)
    if not clock or "2026-09-25T20:09" not in clock:
        return _fail(f"clock {clock}")
    orig = ingest_external_signal(
        text=PENGU,
        msg_id=17,
        received_at="2026-09-25T20:53:00+00:00",
    )
    if orig.get("source_at") != clock:
        return _fail(f"source_at {orig.get('source_at')}")
    if orig.get("add_on") != 0.010139:
        return _fail("addon")
    market = {
        "price": 0.010111,
        "day_used_pct": 120.7,
        "edge_score": 65,
        "m15_ok": False,
        "structure_sl": 0.00993793,
        "review_at": "2026-09-25T20:53:00+00:00",
        "quote_asof": "2026-09-25T20:53:00+00:00",
        "data_status": "DATA_OK",
    }
    rev = review_external_signal(orig, market=market)
    if not (rev.extras or {}).get("signal_stale"):
        return _fail("must mark stale 44min scalp")
    if "застарів" not in " ".join(rev.reasons):
        return _fail(f"stale reason {rev.reasons}")
    if any(r.startswith("ймовірність невдалої") for r in rev.reasons):
        return _fail("must not call NO_TRADE a loss probability")
    plan = compose_trader_plan(orig, rev, market=market, candles=None, asof=market["quote_asof"])
    txt = format_trader_plan(plan)
    if plan.opens_position:
        return _fail("order")
    low = txt.lower()
    if "бак" in low or "пального" in low or "запасу ходу нуль" in low:
        return _fail("fuel tank")
    if "0.009726" in txt or "0.009800" in txt:
        return _fail("invented asian zone")
    if "угоди немає" not in low:
        return _fail("must say no trade now")
    if "застарів" not in low:
        return _fail("stale in card")
    if "edge 65" not in low:
        return _fail("edge rule")
    if "day_used < 40" in low or "day_used < 40%" in txt:
        return _fail("must not wait D1 40%")
    orig2 = ingest_external_signal(text=PENGU, msg_id=99, received_at="2026-09-25T20:54:00+00:00")
    if case_key(orig) != case_key(orig2):
        return _fail("one case")
    kaito = alert_decision(
        status="CONFIRMED",
        entry=0.3559,
        sl=0.35660885,
        tp1=0.35312,
        rr_net=3.01,
    )
    if kaito["send"]:
        return _fail("kaito feed")
    book = SimpleNamespace(
        symbol="VELVETUSDT",
        mode="scalp",
        scenarios=[
            SimpleNamespace(
                status="CONFIRMED",
                direction="LONG",
                setup="bounce",
                entry=0.05985,
                sl=0.05967,
                tp1=0.06047,
                tp2=0.06072,
                rr_net=2.96,
                confirmation="реакція",
                cancel="",
            )
        ],
    )
    if level_book_to_alert(book) is not None:
        return _fail("velvet internal")
    if book.scenarios[0].status != "CONFIRMED":
        return _fail("keep confirmed")
    print("OK: test_t8_contour_review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
