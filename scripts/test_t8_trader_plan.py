#!/usr/bin/env python3
"""Один торговий план на сигнал бота: 4 блоки, без MM-наміру, без фіналу SKIP."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_external_signal import ingest_external_signal, review_external_signal  # noqa: E402
from office_radar import detect_sweep_from_candles  # noqa: E402
from office_range_radar import classify_range_event, detect_range_bounds  # noqa: E402
from office_skip_plan import case_key  # noqa: E402
from office_trader_plan import (  # noqa: E402
    WICK_SWEEP_RETURN,
    WICK_VOLATILE,
    classify_wick,
    compose_trader_plan,
    format_trader_plan,
)
from office_review_position import scanner_enter_opens_position  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl) -> dict:
    return {"open": o, "high": h, "low": l, "close": cl}


def main() -> int:
    if scanner_enter_opens_position("SKIP") is not False:
        return _fail("order")
    raw = "🟢 LONG · PENGUUSDT · 5m\nВхід: 0.010273\nSL: 0.00993793\nTP1: 0.0107756\nSCALP"
    orig = ingest_external_signal(text=raw, msg_id=1, received_at="2026-09-25T20:09:00+00:00")
    rev = review_external_signal(
        orig,
        market={"price": 0.0108, "day_used_pct": 120.7, "edge_score": 35, "m15_ok": False, "structure_sl": 0.00993793},
    )
    plan = compose_trader_plan(
        orig,
        rev,
        market={"price": 0.0108, "day_used_pct": 120.7, "edge_score": 35},
        candles=None,
        asof="2026-09-25T20:09:00+00:00",
    )
    txt = format_trader_plan(plan)
    if plan.opens_position or plan.mm_intent_claimed:
        return _fail("order/mm")
    if "1) Статус первинного сигналу" not in txt:
        return _fail("block1")
    if "2) Чому так" not in txt or "4) Зараз" not in txt:
        return _fail("blocks")
    if "УГОДИ НЕМАЄ" not in txt:
        return _fail("no trade now")
    if "0.009726" in txt or "бак" in txt.lower() or "пального" in txt.lower():
        return _fail("invented fuel")
    if txt.lower().count("1) ") != 1:
        return _fail("must be one telegram card")
    if "ймовірніш" in txt.lower() and "без" not in txt.lower():
        return _fail("forced short odds")
    if "маркет-мейкер" in txt.lower() and "не стверджую" not in txt.lower():
        return _fail("mm claim")
    if "пропускаємо" not in txt.lower() and "SKIP" not in plan.bot_verdict:
        pass
    if "початковий вхід не копіюємо" not in txt.lower() and "застарів" not in txt.lower():
        return _fail("late/skip entry")
    orig2 = ingest_external_signal(text=raw, msg_id=99)
    if case_key(orig) != case_key(orig2) or plan.case_key != case_key(orig):
        return _fail("case")

    bars = [_c(10, 10.2, 9.8, 10.0), _c(10, 10.3, 9.85, 10.1), _c(10.0, 10.5, 9.95, 10.15)]
    w = classify_wick(candles=bars)
    if w["mm_intent_claimed"] or w.get("more_likely_short"):
        return _fail("volatile mm")
    if w["class"] not in (WICK_VOLATILE, WICK_SWEEP_RETURN):
        return _fail(f"wick {w}")

    rng = []
    for i in range(16):
        rng.append(_c(101, 103, 100, 101.5) if i % 2 == 0 else _c(101.5, 102.8, 100.2, 101))
    rng.append(_c(102, 103.6, 101.8, 102.4))
    sw = classify_wick(candles=rng)
    if sw["class"] != WICK_SWEEP_RETURN:
        return _fail(f"sweep class {sw}")
    if "маніпуляц" in str(sw.get("reason") or "").lower() and "mm" in str(sw).lower():
        return _fail("mm word")
    b = detect_range_bounds(rng)
    last = rng[-1]
    ev = classify_range_event(bounds=b, last=last, prev=rng[-2], confirm_candles=rng[-3:])
    if "маркет" in str(ev.get("reason") or "").lower():
        return _fail("range mm")
    _ = detect_sweep_from_candles
    print("OK: test_t8_trader_plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
