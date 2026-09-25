#!/usr/bin/env python3
"""Парсинг зон: пробіл тисяч, десяткові альти, сміття 82–963 невалідне."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_level_parse import (  # noqa: E402
    apply_zone_sanity,
    parse_signal_levels_from_text,
    zone_is_plausible,
)
from office_relay_wizard import _parse_signal_levels_from_text  # noqa: E402
from office_zone_alert import plan_watching_zone_hit  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    tests = [
        "Entry: 0.03826–0.03860",
        "Entry: 81006–81152",
        "Entry: 0.1453–0.1474 (OTE зона)",
        "Жду повернення в зону 0.1445–0.1469",
        "Entry: 0.03826\u22120.03860",
        "OTE SHORT зона 4698\u20134704 технічно відпрацьована",
        "BNBUSDT — ПРОПУСК. OTE зона 655.47\u2013656.34 вже внизу",
        "ПРОПУСК. Чекаю зону: 4698\u20134704",
        "Чекаю зону: `2270.78 – 2273.58` (Bullish FVG) або `2295.50 – 2301.02` (Bearish FVG)",
        "Чекаю зону: 2270.78 - 2273.58",
        "Чекаю зону: 80,328–80,443",
        "Чекаю зону: 82 963–83 434 (SSL знизу + OTE зона після нового імпульсу)",
        "Чекаю зону: 82 963 – 83 434",
    ]
    failed = 0
    for t in tests:
        r = _parse_signal_levels_from_text(t)
        ok = r.get("entry_low") is not None and r.get("entry_high") is not None
        if not ok:
            failed += 1
            print(f"FAIL parse {ascii(t)} -> {r}")
        else:
            print(f"OK  {ascii(t[:50])} -> {r['entry_low']}-{r['entry_high']}")
    btc = parse_signal_levels_from_text(
        "🦁 ПРОПУСК BTCUSDT\nЧекаю зону: 82 963–83 434 (SSL знизу + OTE)"
    )
    if abs(float(btc["entry_low"]) - 82963) > 0.01 or abs(float(btc["entry_high"]) - 83434) > 0.01:
        return _fail(f"BTC space thousands {btc}")
    if zone_is_plausible(82.0, 963.0, 83000):
        return _fail("garbage 82-963 must be implausible vs BTC price")
    if not zone_is_plausible(82963, 83434, 83100):
        return _fail("real BTC zone must be plausible")
    sanit = apply_zone_sanity({"entry_low": 82.0, "entry_high": 963.0}, 83100)
    if sanit.get("entry_low") is not None:
        return _fail("sanity must drop garbage zone")
    plan = plan_watching_zone_hit(
        current_price=83050,
        entry_low=82963,
        entry_high=83434,
        day_used_pct=85.1,
        sl=None,
        symbol="BTCUSDT",
    )
    if not plan.in_zone or "ZONE_REACHED" not in plan.message:
        return _fail("correct BTC zone must ZONE_REACHED")
    if not plan.entry_blocked:
        return _fail("85.1% is not T0 90 so wait — incomplete SL still blocks SIGNAL")
    plan_in = plan_watching_zone_hit(
        current_price=83050,
        entry_low=82963,
        entry_high=83434,
        day_used_pct=85.1,
        sl=82000,
        tp1=84000,
        tp2=85000,
        symbol="BTCUSDT",
    )
    if not plan_in.in_zone:
        return _fail("zone hit")
    if plan_in.entry_blocked:
        return _fail("85.1 < T0 90 must not ATR-block ZONE SIGNAL when SL exists")
    garbage_plan = plan_watching_zone_hit(
        current_price=83050,
        entry_low=82.0,
        entry_high=963.0,
        day_used_pct=40.0,
        symbol="BTCUSDT",
    )
    if garbage_plan.in_zone:
        return _fail("82-963 must not ZONE_REACHED at 83050")
    if failed:
        return 1
    print("OK: test_parse_signal_levels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
