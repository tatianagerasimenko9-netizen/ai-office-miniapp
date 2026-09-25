#!/usr/bin/env python3
"""T0: ZONE_REACHED навіть коли ATR блокує вхід. Офлайн, без мережі."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_zone_alert import (  # noqa: E402
    ZONE_REACHED_COOLDOWN_SEC,
    plan_watching_zone_hit,
    should_emit_zone_reached,
)


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    # IRYS: зона досягнута, ATR мертвий — алерт є, «входь» немає, після алерту expire.
    irys = plan_watching_zone_hit(
        current_price=0.0585,
        entry_low=0.0581,
        entry_high=0.0591,
        day_used_pct=312.0,
        sl=None,
        tp1=None,
        tp2=None,
        symbol="IRYSUSDT",
    )
    if not irys.in_zone:
        return _fail("IRYS in_zone")
    if not irys.entry_blocked or irys.signal_ok:
        return _fail("IRYS must block entry")
    if not irys.expire_after_alert:
        return _fail("IRYS must expire after alert (ATR)")
    if irys.promote_active or irys.run_reanalyze:
        return _fail("IRYS must not promote/reanalyze")
    if "ZONE_REACHED" not in irys.message or "SIGNAL=NO" not in irys.message:
        return _fail("IRYS message flags")
    if "входь" in irys.message.lower():
        return _fail("IRYS must not say входь")
    if "Причина:" not in irys.message:
        return _fail("IRYS needs reason")

    # Ціна поза зоною — тиша, WATCHING не чіпаємо через ATR.
    away = plan_watching_zone_hit(
        current_price=0.0500,
        entry_low=0.0581,
        entry_high=0.0591,
        day_used_pct=312.0,
        symbol="IRYSUSDT",
    )
    if away.in_zone or away.message or away.expire_after_alert:
        return _fail("price outside zone must be silent")

    # Готовий вхід: ATR ок, є SL — SIGNAL=YES і «входь».
    ready = plan_watching_zone_hit(
        current_price=100.0,
        entry_low=99.0,
        entry_high=101.0,
        day_used_pct=40.0,
        sl=98.0,
        tp1=102.0,
        tp2=104.0,
        symbol="SOLUSDT",
    )
    if not ready.signal_ok or not ready.promote_active:
        return _fail("ready setup must allow entry")
    if ready.expire_after_alert:
        return _fail("ready setup must not ATR-expire")
    if "входь!" not in ready.message or "SIGNAL=YES" not in ready.message:
        return _fail("ready setup message")

    # ATR рівно 90 не блокує (було `> 90`, не `>=`).
    edge = plan_watching_zone_hit(
        current_price=100.0,
        entry_low=99.0,
        entry_high=101.0,
        day_used_pct=90.0,
        sl=98.0,
        tp1=102.0,
        tp2=None,
        symbol="SOLUSDT",
    )
    if edge.entry_blocked or not edge.signal_ok:
        return _fail("ATR 90 must not block (legacy >90)")

    # Три цикли монітора з інтервалом 60с — один алерт.
    last = 0.0
    t = 1_000.0
    emits = 0
    for _ in range(3):
        if irys.in_zone and should_emit_zone_reached(last, t):
            emits += 1
            last = t
        t += 60.0
    if emits != 1:
        return _fail(f"monitor loops must emit once, got {emits}")

    print("OK: test_zone_reached_notify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
