#!/usr/bin/env python3
"""T3: повторний SKIP не плодить WATCHING; активна зона далі дає ZONE_REACHED."""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bridge import init_office_db, signal_get_active, signal_upsert  # noqa: E402
from office_watching_dedup import (  # noqa: E402
    SKIP_SCENARIO_EXPIRY_SEC,
    apply_skip_watching_gate,
    expiry_label,
    record_skip_if_valid,
    record_skip_scenario,
    scenario_key,
    should_create_watching_after_skip,
    should_keep_watching_on_skip,
    setup_from_levels,
)
from office_zone_alert import (  # noqa: E402
    ATR_DAY_USED_ENTRY_BLOCK_PCT,
    plan_watching_zone_hit,
    should_emit_zone_reached,
)


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0:
        return _fail("T0 ATR threshold must stay 90")
    if not should_keep_watching_on_skip():
        return _fail("SKIP must not kill active watching")
    if should_create_watching_after_skip(already_active=True, already_skipped=False):
        return _fail("active watching must block new row")
    if should_create_watching_after_skip(already_active=False, already_skipped=True):
        return _fail("repeat skip must block new row")
    if not should_create_watching_after_skip(already_active=False, already_skipped=False):
        return _fail("first skip may open one watching")

    now = 1_800_000_000.0
    setup_a = setup_from_levels("LONG", 100.0, 101.0)
    setup_b = setup_from_levels("LONG", 200.0, 201.0)
    exp = expiry_label(now)
    key_a = scenario_key("solusdt", "1h", setup_a, exp)
    if "SOLUSDT" not in key_a or "1h" not in key_a or setup_a not in key_a or exp not in key_a:
        return _fail("key parts")
    exp2 = expiry_label(now + SKIP_SCENARIO_EXPIRY_SEC + 1)
    if exp == exp2:
        return _fail("expiry bucket must roll")

    db = str(Path(tempfile.mkdtemp()) / "t3.db")
    init_office_db(db)

    g1 = apply_skip_watching_gate(
        db,
        symbol="T3SKIPUSDT",
        direction="LONG",
        entry_low=10.0,
        entry_high=11.0,
        timeframe="1h",
        now_ts=now,
    )
    if not g1["create"]:
        return _fail("first skip should create")
    signal_upsert(
        db,
        signal_id="watch-t3-1",
        symbol="T3SKIPUSDT",
        direction="LONG",
        entry_low=10.0,
        entry_high=11.0,
        sl=9.0,
        tp1=12.0,
        tp2=None,
        rr=2.0,
        status="WATCHING",
        analysis_note="first watching",
    )
    record_skip_scenario(db, g1["key"], symbol="T3SKIPUSDT", timeframe="1h", setup=g1["setup"], expiry=g1["expiry"])

    g2 = apply_skip_watching_gate(
        db,
        symbol="T3SKIPUSDT",
        direction="LONG",
        entry_low=10.0,
        entry_high=11.0,
        timeframe="1h",
        now_ts=now + 60,
    )
    if g2["create"]:
        return _fail("repeat skip same scenario must not create")
    if not g2["already_active"] and not g2["already_skipped"]:
        return _fail("repeat must see active or skipped")

    g_other = apply_skip_watching_gate(
        db,
        symbol="T3SKIPUSDT",
        direction="LONG",
        entry_low=50.0,
        entry_high=51.0,
        timeframe="1h",
        now_ts=now,
    )
    if not g_other["create"]:
        return _fail("different setup may create")

    g_tf = apply_skip_watching_gate(
        db,
        symbol="T3SKIPUSDT",
        direction="LONG",
        entry_low=10.0,
        entry_high=11.0,
        timeframe="4h",
        now_ts=now,
    )
    if g_tf["create"]:
        return _fail("active same setup should not create even on other tf")

    rows = [r for r in signal_get_active(db) if r.get("status") == "WATCHING" and r.get("symbol") == "T3SKIPUSDT"]
    if len(rows) != 1:
        return _fail(f"watching count {len(rows)}")
    if str(rows[0].get("status")) != "WATCHING":
        return _fail("skip must keep WATCHING")

    # Активна зона: ZONE_REACHED не глушиться рішенням SKIP.
    plan = plan_watching_zone_hit(
        current_price=10.5,
        entry_low=10.0,
        entry_high=11.0,
        day_used_pct=40.0,
        sl=9.0,
        tp1=12.0,
        tp2=13.0,
        symbol="T3SKIPUSDT",
    )
    if not plan.in_zone or "ZONE_REACHED" not in plan.message:
        return _fail("active zone must still alert")
    if not should_emit_zone_reached(0.0, time.time()):
        return _fail("zone reached emit")
    if setup_a == setup_b:
        return _fail("setups must differ")

    # Сміття 82–963 не створює WATCHING і не блокує справжню зону через T3.
    g_bad = apply_skip_watching_gate(
        db,
        symbol="BTCUSDT",
        direction="LONG",
        entry_low=82.0,
        entry_high=963.0,
        timeframe="1h",
        now_ts=now,
        current_price=83100.0,
    )
    if g_bad.get("create") or not g_bad.get("invalid_zone"):
        return _fail("invalid zone must not create")
    record_skip_if_valid(db, g_bad, symbol="BTCUSDT", timeframe="1h")
    g_good = apply_skip_watching_gate(
        db,
        symbol="BTCUSDT",
        direction="LONG",
        entry_low=82963.0,
        entry_high=83434.0,
        timeframe="1h",
        now_ts=now,
        current_price=83100.0,
    )
    if not g_good.get("create") or g_good.get("invalid_zone"):
        return _fail("real zone must still create after garbage skip")

    print("OK: test_watching_dedup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
