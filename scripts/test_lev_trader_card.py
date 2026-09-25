#!/usr/bin/env python3
"""Лев-практик: top-down, Asian High/Low, свіп, SL з люфтом, TP1 UPDATE, свіжість."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_external_signal import ingest_external_signal, review_external_signal  # noqa: E402
from office_level_scalp import evaluate_level_book  # noqa: E402
from office_lifecycle import format_manage_update, format_tp1_hit  # noqa: E402
from office_telegram_filter import (  # noqa: E402
    format_opportunity_alert,
    format_px,
    level_book_to_alert,
    range_result_to_alert,
)
from office_topdown import (  # noqa: E402
    DATA_UNAVAILABLE,
    asian_session_range,
    build_topdown,
    calc_sl_with_buffer,
    clock_pair_ua,
    structure_label,
    sweep_story,
)
from office_trader_plan import compose_trader_plan, format_trader_plan  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


PENGU = """
📌 Сигнал бота · ПРЕМІУМ · СКАЛЬП
🟢 LONG · PENGUUSDT · 5m · #17
🕐 23:09 25.09.2026 · поза іменованою сесією · TREND
💰 Вхід:  0.010273 (50%)
🛑 SL:    0.00993793 (3.3%)
🎯 TP1:   0.0107756 (+4.9%)
"""


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl, ts="") -> dict:
    return {"open": o, "high": h, "low": l, "close": cl, "ts": ts}


def _down_d1() -> list:
    """LH/LL: два нижчі хаї і два нижчі лої зі swing wing=2."""
    seq = [
        (2.0, 2.2, 1.8, 2.0),
        (2.0, 2.3, 1.9, 2.1),
        (2.1, 5.0, 2.0, 4.5),
        (4.5, 4.6, 0.5, 1.0),
        (1.0, 1.5, 0.9, 1.2),
        (1.2, 1.6, 1.0, 1.3),
        (1.3, 1.8, 1.1, 1.4),
        (1.4, 4.0, 1.3, 3.5),
        (3.5, 3.6, 0.2, 0.8),
        (0.8, 1.2, 0.4, 0.9),
        (0.9, 1.3, 0.5, 1.0),
        (1.0, 1.4, 0.6, 1.1),
    ]
    out = []
    for i, (o, h, l, cl) in enumerate(seq):
        out.append(_c(o, h, l, cl, f"2026-09-{10 + i:02d}T00:00:00+00:00"))
    return out


def _asia_m15() -> list:
    rows = []
    for h in range(0, 8):
        for m in (0, 15, 30, 45):
            ts = f"2026-09-25T{h:02d}:{m:02d}:00+00:00"
            hi = 0.1315 if (h, m) == (1, 0) else 0.1308
            lo = 0.1298 if (h, m) == (3, 0) else 0.1301
            rows.append(_c(0.1304, hi, lo, 0.1305, ts))
    return rows


def _bsl_m5() -> list:
    return [
        _c(0.1304, 0.1308, 0.1300, 0.1305, "2026-09-25T21:00:00+00:00"),
        _c(0.1305, 0.1309, 0.1301, 0.1304, "2026-09-25T21:05:00+00:00"),
        _c(0.1304, 0.1312, 0.1300, 0.1302, "2026-09-25T21:14:00+00:00"),
    ]


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or SIGNAL_THRESHOLD != 85:
        return _fail("thresholds frozen")

    miss = calc_sl_with_buffer(None, "SHORT")
    if miss.get("data_status") != DATA_UNAVAILABLE or miss.get("sl") is not None:
        return _fail(f"sl missing {miss}")
    packed = calc_sl_with_buffer(0.1312, "SHORT", price=0.1306)
    if packed.get("sl") is None or packed["sl"] <= 0.1312:
        return _fail(f"short sl must be above level {packed}")
    if "люфт" not in str(packed.get("explain") or ""):
        return _fail("sl explain")
    if "0000001" in format_px(packed["sl"]):
        return _fail(f"float junk {format_px(packed['sl'])}")

    empty_td = build_topdown(symbol="AAAUSDT")
    if empty_td["data_status"] != DATA_UNAVAILABLE:
        return _fail("no candles must be DATA_UNAVAILABLE")
    asia_empty = asian_session_range([_c(1, 2, 0.5, 1)])
    if asia_empty["data_status"] != DATA_UNAVAILABLE or asia_empty["high"] is not None:
        return _fail("asia without ts must not invent")

    asia = asian_session_range(_asia_m15())
    if asia["data_status"] != "DATA_OK" or abs(float(asia["high"]) - 0.1315) > 1e-9:
        return _fail(f"asia high {asia}")
    if abs(float(asia["low"]) - 0.1298) > 1e-9:
        return _fail(f"asia low {asia}")

    d1 = structure_label(_down_d1())
    if d1["data_status"] != "DATA_OK" or d1.get("bias") != "SHORT":
        return _fail(f"d1 {d1}")

    sw = sweep_story(_bsl_m5(), direction="SHORT")
    if not sw.get("happened") or "00:14" not in sw.get("line", "") or "0.1309" not in sw.get("line", ""):
        return _fail(f"sweep {sw}")

    td = build_topdown(
        symbol="DEMOUSDT",
        d1=_down_d1(),
        h1=_down_d1(),
        m15=_asia_m15(),
        m5=_bsl_m5(),
        direction="SHORT",
    )
    card = format_opportunity_alert(
        symbol="DEMOUSDT",
        direction="SHORT",
        timeframe="H1",
        entry=0.1306,
        sl=packed["sl"],
        tp1=0.1235,
        tp2=0.1180,
        rr_net=4.8,
        move_pct=5.5,
        structure_line=td["structure_line"],
        sweep_line=td["sweep"]["line"],
        asia_high=td["asia"]["high"],
        asia_low=td["asia"]["low"],
        sl_explain=packed["explain"],
        entry_note="",
        mode="intraday",
        live_price=0.1306,
    )
    for need in (
        "🔴 SHORT · DEMOUSDT · H1",
        "Тип: ІНТРАДЕЙ · Вхід на M15",
        "Ціна зараз: 0.1306",
        "Структура:",
        "Свіп:",
        "Asian High 0.1315",
        "Low 0.1298",
        "BSL знято",
        "SL: " + format_px(packed["sl"]),
        "Ведення:",
        "50–70%",
        "Скасування: H1 свічка закривається вище",
        "Позиція: немає",
    ):
        if need not in card:
            return _fail(f"card missing {need!r} in {card}")
    sl_line = next((ln for ln in card.splitlines() if ln.startswith("SL:")), "")
    if sl_line != f"SL: {format_px(packed['sl'])}":
        return _fail(f"sl must be number only {sl_line!r}")
    if "люфт" in card.split("SL:", 1)[-1].split("\n", 1)[0]:
        return _fail("sl explain leaked")
    if "структурного" in card.lower():
        return _fail("verbal cancel")
    if "21:14" not in card and "00:14" not in card:
        return _fail(f"sweep time {card}")
    for ban in (
        "Чому звернув увагу",
        "Котирування:",
        "умови підтверджені всередині офісу",
        "Не ордер. Угода лише через /position",
    ):
        if ban in card:
            return _fail(f"banned {ban}")
    scalp_card = format_opportunity_alert(
        symbol="AAAUSDT",
        direction="LONG",
        timeframe="M5",
        mode="scalp",
        entry=1.0,
        sl=0.99,
        tp1=1.04,
        rr_net=2.0,
        move_pct=4.0,
    )
    if "Тип: СКАЛЬП · Вхід на M5" not in scalp_card:
        return _fail(scalp_card)
    if "Скасування: M5 свічка закривається нижче 0.99" not in scalp_card:
        return _fail(scalp_card)
    swing_card = format_opportunity_alert(
        symbol="BBBUSDT",
        direction="SHORT",
        timeframe="H4",
        mode="swing",
        entry=10.0,
        sl=10.15,
        tp1=9.4,
        rr_net=2.2,
        move_pct=6.0,
    )
    if "Тип: СВІНГ · Вхід на H4" not in swing_card:
        return _fail(swing_card)
    if "Скасування: H4 свічка закривається вище 10.15" not in swing_card:
        return _fail(swing_card)

    upd = format_manage_update(
        symbol="DEMOUSDT",
        direction="SHORT",
        price=0.1265,
        tp1=0.1235,
        sl=0.1321,
    )
    if "📍 UPDATE" not in upd or "50–70%" not in upd or "0.1321" not in upd:
        return _fail(f"update {upd}")
    hit = format_tp1_hit(
        symbol="DEMOUSDT",
        direction="SHORT",
        entry=0.1306,
        tp1=0.1235,
        tp2=0.1180,
        move_pct=5.5,
    )
    if "✅ TP1" not in hit or "беззбиток: 0.1306" not in hit or "0.118" not in hit:
        return _fail(f"tp1 {hit}")

    clock = clock_pair_ua(
        "2026-09-25T20:09:00+00:00",
        "2026-09-25T20:53:00+00:00",
        scalp=True,
    )
    if "23:09" not in clock or "23:53" not in clock or "44 хв" not in clock:
        return _fail(f"clock {clock}")
    if "для скальпу застарів" not in clock:
        return _fail(f"clock stale {clock}")

    orig = ingest_external_signal(
        text=PENGU,
        msg_id=17,
        received_at="2026-09-25T20:53:00+00:00",
    )
    rev = review_external_signal(
        orig,
        market={
            "price": 0.010111,
            "day_used_pct": 120.7,
            "edge_score": 65,
            "m15_ok": False,
            "structure_sl": 0.00993793,
            "review_at": "2026-09-25T20:53:00+00:00",
            "quote_asof": "2026-09-25T20:53:00+00:00",
            "data_status": "DATA_OK",
        },
    )
    if not (rev.extras or {}).get("signal_stale"):
        return _fail("pengu stale")
    if rev.office_plan is not None:
        return _fail("stale must not copy bot levels as office plan")
    reasons = " ".join(rev.reasons)
    if "23:09" not in reasons or "23:53" not in reasons or "44 хв" not in reasons:
        return _fail(f"freshness first {rev.reasons}")
    plan = compose_trader_plan(orig, rev, market={"price": 0.010111}, asof="2026-09-25T20:53:00+00:00")
    txt = format_trader_plan(plan)
    if "Котирування:" in txt:
        return _fail("iso quote leaked")
    if "для скальпу застарів" not in txt:
        return _fail(txt)
    if plan.opens_position:
        return _fail("review is not /position")

    kaito = SimpleNamespace(
        symbol="KAITOUSDT",
        mode="scalp",
        scenarios=[
            SimpleNamespace(
                status="CONFIRMED",
                direction="SHORT",
                setup="bounce",
                entry=0.3559,
                sl=0.35660885,
                tp1=0.35312,
                tp2=None,
                rr_net=3.01,
                confirmation="реакція",
                cancel="",
                sl_note="вище круглого + люфт",
            )
        ],
    )
    if level_book_to_alert(kaito) is not None:
        return _fail("kaito <3% stays internal")
    if kaito.scenarios[0].status != "CONFIRMED":
        return _fail("kaito status")
    silent = SimpleNamespace(status="RANGE_WATCHING", card=None, symbol="BTCUSDT", event="INSIDE")
    if range_result_to_alert(silent) is not None:
        return _fail("inside")

    reclaim = [
        _c(101.0, 103.0, 100.2, 101.5),
        _c(101.5, 102.8, 100.4, 101.0),
        _c(101.0, 103.0, 100.2, 101.5),
        _c(101.5, 102.8, 100.4, 101.0),
        _c(101.0, 103.0, 100.2, 101.5),
        _c(101.5, 102.8, 100.4, 101.0),
        _c(101.0, 103.0, 100.2, 101.5),
        _c(101.5, 102.8, 100.4, 101.0),
        _c(101.0, 103.0, 100.2, 101.5),
        _c(101.5, 102.8, 100.4, 101.0),
        _c(101.0, 103.0, 100.2, 101.5),
        _c(101.5, 102.8, 100.4, 101.0),
        _c(101.0, 103.0, 100.2, 101.5),
        _c(101.5, 102.8, 100.4, 101.0),
        _c(101.0, 103.0, 100.2, 101.5),
        _c(101.5, 102.8, 100.4, 101.0),
        _c(100.4, 101.2, 99.6, 100.8),
    ]
    book = evaluate_level_book(
        symbol="ETHUSDT",
        candles=reclaim,
        confirm_candles=reclaim[-3:],
        price=100.8,
        day_used_pct=30,
        edge_score=90,
        mode="intraday",
        d1_candles=_down_d1(),
        m15_candles=_asia_m15(),
        m5_candles=_bsl_m5(),
    )
    if book.opens_position:
        return _fail("level order")
    td_book = (book.extras or {}).get("topdown") or {}
    if not isinstance(td_book, dict):
        return _fail("topdown missing")

    print("OK: test_lev_trader_card")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
