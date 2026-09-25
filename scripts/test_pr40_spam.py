#!/usr/bin/env python3
"""PR40: WATCHING/NEAR не в Telegram, dedup символу, cooldown 60s. Логіка PR39 жива."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_lifecycle import db_status_for  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_news_agent import DATA_UNAVAILABLE, format_nazar_update  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_telegram_filter import MIN_ALERT_MOVE_PCT, alert_decision  # noqa: E402
from office_telegram_policy import (  # noqa: E402
    KIND_NEWS,
    KIND_SIGNAL,
    KIND_SL,
    KIND_SWEEP_NEAR,
    KIND_TP,
    KIND_WATCHING,
    TELEGRAM_COOLDOWN_SEC,
    allow_proactive_telegram,
    mark_cycle_sent,
    preferred_scan_mode,
    sweep_near_to_telegram,
    watching_to_telegram,
)
from office_topdown import (  # noqa: E402
    COUNTER_TREND_MIN_RR,
    asian_session_range,
    calc_sl_with_buffer,
    plan_entry_point,
    structure_confluence,
    sweep_story,
)
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl, ts="") -> dict:
    return {"open": o, "high": h, "low": l, "close": cl, "ts": ts}


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("atr frozen")
    if SIGNAL_THRESHOLD != 85 or MIN_ALERT_MOVE_PCT != 3.0 or MIN_RR < 1.5 or MIN_RR > 1.54:
        return _fail("edge/3%/rr frozen")
    if COUNTER_TREND_MIN_RR != 2.5:
        return _fail("pr39 rr")
    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("order")
    if TELEGRAM_COOLDOWN_SEC != 60.0:
        return _fail("cooldown")
    if watching_to_telegram() or sweep_near_to_telegram():
        return _fail("watching/near must be silent")

    w = allow_proactive_telegram(kind=KIND_WATCHING, symbol="AKEUSDT")
    if w.get("send"):
        return _fail("watching telegram")
    n = allow_proactive_telegram(kind=KIND_SWEEP_NEAR, symbol="AKEUSDT")
    if n.get("send"):
        return _fail("near telegram")
    if db_status_for("WAITING_SWEEP") != "WATCHING" or db_status_for("NEAR_SWEEP") != "WATCHING":
        return _fail("db watching")

    sent: set = set()
    now = 1_000.0
    ok = allow_proactive_telegram(
        kind=KIND_SIGNAL, symbol="AKEUSDT", sent_symbols=sent, last_feed_ts=0.0, now_ts=now
    )
    if not ok.get("send"):
        return _fail(f"first signal {ok}")
    mark_cycle_sent(sent, "AKEUSDT")
    dup = allow_proactive_telegram(
        kind=KIND_SIGNAL, symbol="akeusdt", sent_symbols=sent, last_feed_ts=now, now_ts=now + 1
    )
    if dup.get("send"):
        return _fail("dup symbol")
    cool = allow_proactive_telegram(
        kind=KIND_SIGNAL, symbol="SOLUSDT", sent_symbols=sent, last_feed_ts=now, now_ts=now + 30
    )
    if cool.get("send"):
        return _fail("cooldown 30s")
    later = allow_proactive_telegram(
        kind=KIND_SIGNAL, symbol="SOLUSDT", sent_symbols=sent, last_feed_ts=now, now_ts=now + 61
    )
    if not later.get("send"):
        return _fail(f"after 60s {later}")
    tp = allow_proactive_telegram(
        kind=KIND_TP, symbol="AKEUSDT", sent_symbols=sent, last_feed_ts=now, now_ts=now + 1
    )
    sl = allow_proactive_telegram(kind=KIND_SL, symbol="AKEUSDT", last_feed_ts=now, now_ts=now + 1)
    news = allow_proactive_telegram(kind=KIND_NEWS, symbol="", last_feed_ts=now, now_ts=now + 1)
    if not (tp.get("send") and sl.get("send") and news.get("send")):
        return _fail("priority")
    if preferred_scan_mode(["scalp", "intraday"]) != "intraday":
        return _fail("prefer h1")
    if preferred_scan_mode(["scalp"]) != "scalp":
        return _fail("scalp only")

    kaito = alert_decision(status="CONFIRMED", entry=0.3559, sl=0.35660885, tp1=0.35312, rr_net=3.01)
    if kaito["send"]:
        return _fail("kaito")
    wait = alert_decision(
        status="WATCHING", entry=0.032889, sl=0.0319, tp1=0.0350, rr_net=4.0, entry_mode="WAITING_SWEEP"
    )
    if wait["send"]:
        return _fail("waiting decision")
    silent = format_nazar_update(data_status=DATA_UNAVAILABLE)
    if silent is not None:
        return _fail("nazar")

    miss = calc_sl_with_buffer(None, "SHORT")
    if miss.get("sl") is not None:
        return _fail("sl unavailable")
    packed = calc_sl_with_buffer(0.1312, "SHORT", price=0.1306)
    if packed.get("sl") is None or packed["sl"] <= 0.1312:
        return _fail("gerchik")
    wild = asian_session_range(
        [_c(0.0328, 0.040989, 0.0324, 0.032889, f"2026-09-25T{h:02d}:00:00+00:00") for h in range(0, 8)],
        asof="2026-09-25T12:00:00+00:00",
        current_price=0.032889,
    )
    if wild.get("high") is not None:
        return _fail("asia 15%")
    conf = structure_confluence(
        d1={"bias": "LONG", "label": "висхідний тренд (HH/HL)", "data_status": "DATA_OK"},
        h1={"bias": "SHORT", "label": "низхідний тренд (LH/LL)", "data_status": "DATA_OK"},
        direction="LONG",
    )
    if not conf.get("requires_m15_bos"):
        return _fail("bos")
    impulse_up = [
        _c(0.0320, 0.0322, 0.0319, 0.0321, "2026-09-25T09:00:00+00:00"),
        _c(0.0320, 0.0331, 0.03195, 0.0330, "2026-09-25T09:15:00+00:00"),
    ]
    pb = plan_entry_point(direction="LONG", price=0.032889, candles=impulse_up, tf="M15")
    if "відкат 50%" not in str(pb.get("card_note") or ""):
        return _fail(pb)
    sw = sweep_story(
        [
            _c(0.1304, 0.1308, 0.1300, 0.1305, "2026-09-25T21:00:00+00:00"),
            _c(0.1305, 0.1309, 0.1301, 0.1304, "2026-09-25T21:05:00+00:00"),
            _c(0.1304, 0.1312, 0.1300, 0.1302, "2026-09-25T21:14:00+00:00"),
        ],
        direction="SHORT",
    )
    if not sw.get("happened"):
        return _fail("sweep story")

    print("OK: test_pr40_spam")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
