#!/usr/bin/env python3
"""Telegram: лише сетап ≥3% до TP1, без dump рівнів і без TP2 None."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_radar import MIN_RR  # noqa: E402
from office_telegram_filter import (  # noqa: E402
    MIN_ALERT_MOVE_PCT,
    alert_decision,
    format_opportunity_alert,
    format_px,
    level_book_to_alert,
    move_pct_to_tp,
    range_result_to_alert,
)
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or SIGNAL_THRESHOLD != 85:
        return _fail("thresholds")
    if MIN_ALERT_MOVE_PCT != 3.0:
        return _fail("3pct")
    if "0000005" in format_px(0.34280000000000005):
        return _fail(f"float junk {format_px(0.34280000000000005)}")
    if format_px(None) or format_px("None"):
        return _fail("none")
    # KAITO-подібний тісний SHORT: ~0.78% — не в стрічку, TP не натягуємо.
    kaito = alert_decision(
        status="CONFIRMED",
        entry=0.3559,
        sl=0.35660885,
        tp1=0.35312,
        rr_net=3.01,
    )
    if kaito["send"] or move_pct_to_tp(entry=0.3559, tp=0.35312) >= 3:
        return _fail(f"kaito {kaito}")
    ake = alert_decision(
        status="CONFIRMED",
        entry=0.033824,
        sl=0.0339389,
        tp1=0.03358666,
        rr_net=1.535,
    )
    if ake["send"]:
        return _fail("ake 0.7% must not alert even if RR>1.5")
    if MIN_RR > 1.54:
        return _fail("do not raise MIN_RR")
    watching = alert_decision(status="WATCHING", entry=1, sl=0.99, tp1=1.04, rr_net=2)
    if watching["send"]:
        return _fail("watching not in feed")
    ok = alert_decision(status="CONFIRMED", entry=100.0, sl=98.8, tp1=103.2, rr_net=2.0)
    if not ok["send"]:
        return _fail(f"3%+ should send {ok}")
    txt = format_opportunity_alert(
        symbol="DEMOUSDT",
        direction="LONG",
        timeframe="M5",
        setup="bounce",
        why="повернення вище зони після свіпу",
        entry=0.1000,
        sl=0.0988,
        tp1=0.1032,
        tp2=None,
        rr_net=2.1,
        cancel="закриття нижче зони",
        move_pct=3.2,
    )
    if "None" in txt or "підтримка" in txt.lower() and txt.count("підтримка") > 1:
        return _fail("dump")
    if "TP2" in txt:
        return _fail("tp2 none leaked")
    if "вісім" in txt or txt.count("Рівень:") >= 2:
        return _fail("levels dump")
    book = SimpleNamespace(
        symbol="VELVETUSDT",
        mode="intraday",
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
                cancel="закриття нижче",
            )
        ],
    )
    if level_book_to_alert(book) is not None:
        return _fail("velvet 1% must stay internal")
    wide = SimpleNamespace(
        symbol="SOLUSDT",
        mode="intraday",
        scenarios=[
            SimpleNamespace(
                status="CONFIRMED",
                direction="LONG",
                setup="bounce",
                entry=100.0,
                sl=98.8,
                tp1=103.5,
                tp2=None,
                rr_net=2.4,
                confirmation="свіп і повернення",
                cancel="закриття нижче зони",
            )
        ],
    )
    alert = level_book_to_alert(wide)
    if not alert or "SOLUSDT" not in alert or "None" in alert:
        return _fail(f"wide {alert}")
    silent = SimpleNamespace(status="RANGE_WATCHING", card=None, symbol="BTCUSDT", event="INSIDE")
    if range_result_to_alert(silent) is not None:
        return _fail("inside range must not telegram")
    print("OK: test_t8_telegram_filter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
