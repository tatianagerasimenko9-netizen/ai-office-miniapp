#!/usr/bin/env python3
"""PR68: канонічний сценарій, lifecycle/hydrate і event dedup без Telegram."""
from __future__ import annotations

import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["OFFICE_DEPO_USDT"] = "1000"
os.environ["OFFICE_EXINFO_SEED"] = "1"

from office_alert_gate import (  # noqa: E402
    apply_setup_event,
    get_setup_state,
    hydrate_alert_gate_from_db,
    may_emit_telegram,
    reset_alert_gate,
)
from office_bridge import init_office_db, signal_get_active, signal_update, signal_upsert  # noqa: E402
from office_confluence import (  # noqa: E402
    evaluate_confluence,
    hydrate_live_from_db,
    live_items,
    mark_live,
    reset_live,
)
from office_desk_card import desk_entry_gate, prepare_desk_send  # noqa: E402
from office_exchange_info import get_symbol_filters, reset_exchange_info  # noqa: E402
from office_scenario_memory import stamp_scenario_note  # noqa: E402
from office_telegram_policy import reset_trade_telegram_dedup, should_send_trade_telegram  # noqa: E402


def _fail(msg: object) -> int:
    print(f"FAIL: {msg}")
    return 1


def _candidates(lo: float, *, basis: str = "same") -> list[dict[str, object]]:
    return [
        {
            "tag": "ob",
            "lo": lo,
            "hi": 76719.48,
            "tf": "H1",
            "label": "OB H1",
            "origin_ts": f"{basis}-ob",
        },
        {
            "tag": "fib_h4",
            "lo": max(lo, 75610.0),
            "hi": 76500.0,
            "tf": "H4",
            "label": "Фібо H4",
            "origin_ts": f"{basis}-fib",
        },
    ]


def _eval(symbol: str, direction: str, timeframe: str, lo: float, *, basis: str = "same") -> dict:
    return evaluate_confluence(
        symbol=symbol,
        direction=direction,
        timeframe=timeframe,
        candidates=_candidates(lo, basis=basis),
        now_ts=100.0,
    )


def main() -> int:
    reset_live()
    first = _eval("BTCUSDT", "LONG", "H1", 75532.82)
    mark_live(
        first["scenario_id"],
        {
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "timeframe": "H1",
            "zone_lo": first["zone_lo"],
            "zone_hi": first["zone_hi"],
            "entry_low": first["zone_lo"],
            "entry_high": first["zone_hi"],
            "basis": first["market_basis"],
            "scenario_id": first["scenario_id"],
            "ts": 100.0,
        },
    )
    drift = _eval("BTCUSDT", "LONG", "H1", 75610.0)
    if drift.get("send_card") or drift.get("scenario_id") != first.get("scenario_id"):
        return _fail(("93.5% drift split", first, drift))

    for symbol, direction, timeframe, basis in (
        ("ETHUSDT", "LONG", "H1", "same"),
        ("BTCUSDT", "SHORT", "H1", "same"),
        ("BTCUSDT", "LONG", "H4", "same"),
        ("BTCUSDT", "LONG", "H1", "other"),
    ):
        probe = _eval(symbol, direction, timeframe, 75610.0, basis=basis)
        if not probe.get("send_card") or probe.get("scenario_id") == first.get("scenario_id"):
            return _fail(("independent identity merged", symbol, direction, timeframe, basis, probe))
    print("OK canonical overlap; symbol/direction/TF/basis remain independent")

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_office_db(db)
        sid = str(first["scenario_id"])
        note = stamp_scenario_note(
            f"ckey={first['zone_key']}",
            origin="desk",
            timeframe="H1",
            scenario_id=sid,
            basis=str(first["market_basis"]),
        )
        signal_upsert(
            db,
            signal_id=sid,
            symbol="BTCUSDT",
            direction="LONG",
            entry_low=first["zone_lo"],
            entry_high=first["zone_hi"],
            sl=74500.0,
            tp1=78000.0,
            tp2=None,
            rr=1.5,
            status="WATCHING",
            analysis_note=note,
        )
        for status in ("ZONE_REACHED", "CONFIRMED"):
            signal_update(db, signal_id=sid, status=status)
            reset_live()
            if hydrate_live_from_db(db) != 1:
                return _fail(f"hydrate {status}")
            hydrated = dict(live_items()).get(sid) or {}
            if hydrated.get("status") != status:
                return _fail(("lifecycle lost", status, hydrated))

        reset_live()
        redetected = _eval("BTCUSDT", "LONG", "H1", 75610.0)
        prep = prepare_desk_send(
            db_path=db,
            symbol="BTCUSDT",
            direction="LONG",
            timeframe="H1",
            entry=redetected.get("entry"),
            sl=74500.0,
            tp1=78000.0,
            atr_h1=500.0,
            confluence=redetected,
            lev_note="перевірена H1 основа",
        )
        row = signal_get_active(db)[0]
        if prep.get("send") or prep.get("scenario_id") != sid or row.get("status") != "CONFIRMED":
            return _fail(("redetection reset lifecycle", prep, row))
        if abs(float(row.get("entry_low") or 0) - 75610.0) > 1e-6:
            return _fail(("zone drift not refreshed", row))

        reset_alert_gate()
        hydrate_alert_gate_from_db(db)
        if may_emit_telegram(key=sid, intent="CONFIRM", ltf_confirmed=True).get("send"):
            return _fail("CONFIRMED replay after hydrate")

        signal_update(db, signal_id=sid, status="CANCELLED", outcome="CANCELLED")
        reset_live()
        reset_alert_gate()
        hydrate_live_from_db(db)
        hydrate_alert_gate_from_db(db)
        if (dict(live_items()).get(sid) or {}).get("status") != "CANCELLED":
            return _fail("CANCELLED hydrate")
        if get_setup_state(sid).get("state") != "CANCELLED":
            return _fail(("alert lifecycle hydrate", get_setup_state(sid)))
        apply_setup_event(sid, "CANCELLED")
        print("OK WATCHING→ZONE_REACHED→CONFIRMED→CANCELLED survives redetection/hydrate")
    finally:
        os.unlink(db)

    reset_trade_telegram_dedup()
    d1 = should_send_trade_telegram(
        text="Entry 75 532.82",
        kind="signal",
        symbol="BTCUSDT",
        canonical_id=str(first["scenario_id"]),
        event="SIGNAL_ENTRY",
        now_ts=1.0,
    )
    d2 = should_send_trade_telegram(
        text="Entry 75 610",
        kind="signal",
        symbol="BTCUSDT",
        canonical_id=str(first["scenario_id"]),
        event="SIGNAL_ENTRY",
        now_ts=2000.0,
    )
    d3 = should_send_trade_telegram(
        text="Підтверджено",
        kind="CONFIRM",
        symbol="BTCUSDT",
        canonical_id=str(first["scenario_id"]),
        event="CONFIRM",
        now_ts=3.0,
    )
    other = _eval("BTCUSDT", "LONG", "H1", 75610.0, basis="new-event")
    d4 = should_send_trade_telegram(
        text="Entry 75 610",
        kind="signal",
        symbol="BTCUSDT",
        canonical_id=str(other["scenario_id"]),
        event="SIGNAL_ENTRY",
        now_ts=4.0,
    )
    if not d1.get("send") or d2.get("send") or not d3.get("send") or not d4.get("send"):
        return _fail(("event dedup", d1, d2, d3, d4))
    print("OK dedup = canonical scenario + event")

    reset_exchange_info()
    manta = get_symbol_filters("MANTAUSDT")
    if manta.get("tickSize") != Decimal("0.0000100"):
        return _fail(("MANTA tickSize", manta))
    blocked = desk_entry_gate(
        symbol="MANTAUSDT",
        direction="LONG",
        entry=0.060000,
        sl=0.059300,
        tp1=0.061278,
        atr_h1=0.000500,
    )
    if blocked.get("send") or "2.13" not in str(blocked.get("reason")) or "< 3%" not in str(blocked.get("reason")):
        return _fail(("MANTA 3% fail-closed", blocked))
    print("OK MANTA tickSize=0.0000100; TP1 2.13% < 3% remains blocked")
    print("OK: test_pr68_canonical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
