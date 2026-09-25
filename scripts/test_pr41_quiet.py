#!/usr/bin/env python3
"""PR41: проактивно лише SIGNAL_ENTRY / TRADE_* / NEWS / debrief. ZONE_REACHED SIGNAL=NO — тиша."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_telegram_filter import MIN_ALERT_MOVE_PCT, alert_decision  # noqa: E402
from office_telegram_policy import (  # noqa: E402
    EVENT_EVENING_DEBRIEF,
    EVENT_NEWS_CRITICAL,
    EVENT_SIGNAL_ENTRY,
    EVENT_TRADE_CLOSED,
    EVENT_TRADE_UPDATE,
    KIND_NEWS,
    KIND_SIGNAL,
    KIND_SL,
    KIND_TP,
    KIND_WATCHING,
    LLM_CALLS_SAVED_PER_ZONE_SKIP,
    PROACTIVE_ALLOWED,
    allow_proactive_telegram,
    may_send_proactive,
)
from office_zone_alert import (  # noqa: E402
    format_zone_signal_entry,
    plan_watching_zone_hit,
    zone_reached_to_telegram,
)


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0 or SIGNAL_THRESHOLD != 85:
        return _fail("frozen atr/edge")
    if MIN_ALERT_MOVE_PCT != 3.0 or MIN_RR < 1.5:
        return _fail("frozen 3%/rr")
    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("order")
    if LLM_CALLS_SAVED_PER_ZONE_SKIP != 2:
        return _fail("llm saved count")
    need = {
        EVENT_SIGNAL_ENTRY,
        EVENT_TRADE_UPDATE,
        EVENT_TRADE_CLOSED,
        EVENT_NEWS_CRITICAL,
        EVENT_EVENING_DEBRIEF,
    }
    if PROACTIVE_ALLOWED != need:
        return _fail(f"allowed {PROACTIVE_ALLOWED}")
    if may_send_proactive("ZONE_REACHED") or may_send_proactive("SKIP"):
        return _fail("zone/skip proactive")
    if not may_send_proactive("ZONE_REACHED", reply_to_user=True):
        return _fail("user reply")
    if not may_send_proactive(EVENT_SIGNAL_ENTRY):
        return _fail("signal entry")

    koru = plan_watching_zone_hit(
        current_price=21.56,
        entry_low=21.56,
        entry_high=21.56,
        day_used_pct=82.0,
        sl=None,
        tp1=None,
        tp2=None,
        symbol="KORUUSDT",
    )
    if not koru.in_zone or koru.signal_ok or zone_reached_to_telegram(koru):
        return _fail("koru must be silent telegram")
    if "SIGNAL=NO" not in koru.message:
        return _fail("koru db message")

    apr = plan_watching_zone_hit(
        current_price=0.1523,
        entry_low=0.1523,
        entry_high=0.1523,
        day_used_pct=150.0,
        sl=None,
        tp1=None,
        tp2=None,
        symbol="APRUSDT",
    )
    if zone_reached_to_telegram(apr) or not apr.expire_after_alert:
        return _fail("apr atr silent")

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
    if not zone_reached_to_telegram(ready):
        return _fail("ready must be signal entry")
    card = format_zone_signal_entry(
        symbol="SOLUSDT",
        current_price=100.0,
        entry_low=99.0,
        entry_high=101.0,
        sl=98.0,
        tp1=102.0,
        tp2=104.0,
    )
    if "ZONE_REACHED" in card or "SIGNAL=NO" in card:
        return _fail("card must not be zone_reached text")

    z = allow_proactive_telegram(kind="zone_reached", symbol="KORUUSDT")
    if z.get("send"):
        return _fail("zone kind")
    if allow_proactive_telegram(kind=KIND_WATCHING, symbol="KORUUSDT").get("send"):
        return _fail("watching")
    ok = allow_proactive_telegram(kind=KIND_SIGNAL, symbol="AKEUSDT", last_feed_ts=0.0, now_ts=10.0)
    if not ok.get("send"):
        return _fail(f"signal {ok}")
    for k in (KIND_TP, KIND_SL, KIND_NEWS):
        g = allow_proactive_telegram(kind=k, symbol="AKEUSDT", last_feed_ts=10.0, now_ts=11.0)
        if not g.get("send"):
            return _fail(f"prio {k}")
    skip_scan = allow_proactive_telegram(kind="skip", symbol="KORUUSDT")
    if skip_scan.get("send"):
        return _fail("skip scan")
    kaito = alert_decision(status="CONFIRMED", entry=0.3559, sl=0.35660885, tp1=0.35312, rr_net=3.01)
    if kaito["send"]:
        return _fail("kaito <3%")
    print("OK: test_pr41_quiet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
