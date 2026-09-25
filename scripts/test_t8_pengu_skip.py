#!/usr/bin/env python3
"""PENGU: один зовнішній сигнал, SKIP, альтернативи без вигаданих зон і без 2×ATR."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import explain_atr_day_used, new_daily_bar_resets_atr  # noqa: E402
from office_bridge import _fetchall, init_office_db  # noqa: E402
from office_btc_liquidations import BtcForceOrderBook  # noqa: E402
from office_external_signal import ingest_external_signal, review_external_signal  # noqa: E402
from office_skip_plan import (  # noqa: E402
    build_skip_plan,
    case_key,
    format_skip_plan,
    persist_skip_case,
    premium_score_allows_entry,
)
from office_t7_health import diagnose_force_order_snapshot  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402

PENGU = """
📌 Сигнал бота · ПРЕМІУМ · СКАЛЬП
🟢 LONG · PENGUUSDT · 5m
💰 Вхід:  0.010273
➕ Добір: 0.010139
🛑 SL:    0.00993793
🎯 TP1:   0.0107756
🎯 TP2:   0.011172
🎯 TP3:   0.0119484
"""


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl) -> dict:
    return {"open": o, "high": h, "low": l, "close": cl}


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0:
        return _fail("90")
    if premium_score_allows_entry(16, 20):
        return _fail("premium is not entry")
    if new_daily_bar_resets_atr():
        return _fail("D1 entry")
    exp = explain_atr_day_used(120.7)
    if exp["excess_pct_over_atr"] != 20.7 or exp["more_than_double_atr"]:
        return _fail("not double")

    orig = ingest_external_signal(text=PENGU, msg_id=1, received_at="2026-09-25T20:09:00+00:00")
    orig2 = ingest_external_signal(text=PENGU, msg_id=2, received_at="2026-09-25T20:11:00+00:00")
    if case_key(orig) != case_key(orig2):
        return _fail("same bot card must be one case")

    market = {
        "price": 0.010273,
        "day_used_pct": 120.7,
        "edge_score": 35,
        "m15_ok": False,
        "structure_sl": 0.00993793,
    }
    rev1 = review_external_signal(orig, market=market)
    rev2 = review_external_signal(orig2, market=market)
    t7 = BtcForceOrderBook().snapshot()
    d = diagnose_force_order_snapshot(t7)
    if d.get("idle_cold_means_no_liquidations") is not False:
        return _fail("t7")

    p1 = build_skip_plan(
        orig, rev1, market=market, t7_snap=t7, candles=None, premium_score=16, version=1
    )
    p2 = build_skip_plan(
        orig2, rev2, market=market, t7_snap=t7, candles=None, premium_score=16, version=2
    )
    if p1.case_key != p2.case_key:
        return _fail("case")
    if p1.opens_position or p1.premium_allows_entry or p1.invented_levels:
        return _fail("flags")
    if p1.alt_a.get("zone_low") is not None or p1.alt_a.get("invented"):
        return _fail("no invented LONG zone from chat")
    if "20.7" not in " ".join(p1.why):
        return _fail(f"why atr {p1.why}")
    if "удвічі" in " ".join(p1.why) and "не «більш ніж удвічі»" not in " ".join(p1.why):
        return _fail("double wording")
    txt = format_skip_plan(p1)
    if "0.009726" in txt or "0.009800" in txt:
        return _fail("must not copy Lev chat zones")
    if "Цей вхід пропускаємо" not in txt:
        return _fail("skip headline")
    if "Ось що відстежуємо" not in txt or "Ось за якої події повідомимо" not in txt:
        return _fail("watch/event headlines")
    if "forceOrder" not in txt and "ліквідац" not in txt.lower():
        return _fail("liq note")
    if not p1.liquidations.get("kind") == "forceOrder_actual_not_map":
        return _fail("liq kind")
    if p1.liquidations.get("usable_now"):
        return _fail("idle_cold must not be used as liq map")
    if p1.current != "SKIP":
        return _fail("current")

    db = str(Path(tempfile.mkdtemp()) / "pengu.db")
    init_office_db(db)
    r1 = persist_skip_case(db, p1, now_ts=1_800_000_000.0)
    r2 = persist_skip_case(db, p2, now_ts=1_800_000_120.0)
    n_watch = _fetchall(db, "SELECT COUNT(*) FROM office_signals WHERE status='WATCHING'")[0][0]
    n_ev = _fetchall(
        db, "SELECT COUNT(*) FROM office_events WHERE event_type='T8_SKIP_CASE'"
    )[0][0]
    n_j = _fetchall(db, "SELECT COUNT(*) FROM trade_journal")[0][0]
    if n_j != 0:
        return _fail("journal")
    if n_watch != 0:
        return _fail(f"no candles => no invented watching {n_watch} {r1} {r2}")
    if n_ev != 2:
        return _fail(f"two analysis versions {n_ev}")

    bars = []
    for i in range(16):
        bars.append(_c(0.0099, 0.0102, 0.0097, 0.0100) if i % 2 == 0 else _c(0.0100, 0.01015, 0.00975, 0.0099))
    p3 = build_skip_plan(orig, rev1, market=market, t7_snap=t7, candles=bars, version=1)
    r3 = persist_skip_case(db, p3, now_ts=1_800_000_200.0)
    r4 = persist_skip_case(db, p3, now_ts=1_800_000_260.0)
    n_watch2 = _fetchall(db, "SELECT COUNT(*) FROM office_signals WHERE status='WATCHING'")[0][0]
    if n_watch2 != 1:
        return _fail(f"one watching {n_watch2} {r3} {r4}")
    if r4.get("created"):
        return _fail("second persist must not create")

    print("OK: test_t8_pengu_skip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
