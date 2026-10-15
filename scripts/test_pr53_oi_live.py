#!/usr/bin/env python3
"""PR53: OI/funding у лог; forceOrder не в SIGNAL_ENTRY."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(m: str) -> int:
    print(f"FAIL: {m}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90 or SIGNAL_THRESHOLD != 85 or MIN_RR < 1.5:
        return _fail("frozen")
    src = (ROOT / "office_relay_wizard.py").read_text(encoding="utf-8")
    sig = src.find('if res.status == "SIGNAL":')
    card = src.find("[radar] SIGNAL card", sig)
    if sig < 0 or card < 0:
        return _fail("radar SIGNAL not found")
    radar_send = src[sig:card]
    if "format_radar_liq_summary" in radar_send:
        return _fail("forceOrder still glued to SIGNAL card")
    watch = src.find('status="WATCHING"')
    watch_end = src.find("[radar] WATCHING", watch)
    if watch < 0 or watch_end < 0:
        return _fail("WATCHING block not found")
    if "format_radar_liq_summary" in src[watch:watch_end]:
        return _fail("forceOrder still in WATCHING analysis_note")
    if "[oi] BTCUSDT" not in src:
        return _fail("oi log missing")
    print("OK: test_pr53_oi_live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
