#!/usr/bin/env python3
"""PR38: Назар fail-closed, T7 reconnect/health, /api/state, картка %/RR."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_btc_liquidations import (  # noqa: E402
    MAX_RECONNECT_ATTEMPTS,
    STUCK_CONNECTING_SEC,
    reconnect_plan,
)
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_news_agent import (  # noqa: E402
    DATA_EMPTY,
    DATA_UNAVAILABLE,
    format_nazar_update,
    nazar_forbidden_in,
)
from office_t7_health import t7_health_payload  # noqa: E402
from office_telegram_filter import format_opportunity_alert, level_book_to_alert  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402
from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_telegram_filter import MIN_ALERT_MOVE_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("atr frozen")
    if SIGNAL_THRESHOLD != 85 or MIN_ALERT_MOVE_PCT != 3.0 or MIN_RR < 1.5:
        return _fail("edge/3%/rr frozen")
    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("order")

    silent = format_nazar_update(data_status=DATA_UNAVAILABLE)
    if silent is not None:
        return _fail(f"timeout must silence {silent}")
    neu = format_nazar_update(data_status=DATA_EMPTY, minutes_to_event=999)
    if neu is None or "нейтральн" not in neu.lower():
        return _fail(f"empty {neu}")
    if nazar_forbidden_in(neu):
        return _fail("neutral forbids")
    warn = format_nazar_update(
        data_status="DATA_OK",
        minutes_to_event=25,
        event_name="CPI",
        event_time_ua="15:30",
    )
    if warn is None or "CPI" not in warn or "15:30" not in warn or "УВАГА" not in warn:
        return _fail(f"event {warn}")
    if nazar_forbidden_in(warn):
        return _fail("warn forbids")

    stuck = reconnect_plan(state="connecting", age_sec=STUCK_CONNECTING_SEC + 1, attempt=3)
    if not stuck.get("reconnect") or stuck.get("delay_sec") != 60.0:
        return _fail(f"stuck {stuck}")
    if stuck.get("attempt") != 3 or stuck.get("max_attempts") != MAX_RECONNECT_ATTEMPTS:
        return _fail(f"attempts {stuck}")
    if "reconnect 3/10" not in str(stuck.get("log") or ""):
        return _fail(f"log {stuck}")
    if stuck.get("means_no_liquidations"):
        return _fail("connecting is not no-liq")
    quiet = reconnect_plan(state="idle_cold", age_sec=1801, attempt=1)
    if not quiet.get("quiet_log") or "ринок тихий" not in str(quiet.get("log") or ""):
        return _fail(f"quiet {quiet}")

    hp = t7_health_payload({"connected": False, "loop_started": True, "reconnects": 0, "last_error": ""})
    if hp.get("t7_status") != "connecting":
        return _fail(f"health {hp}")
    if hp.get("connecting_means_no_liquidations"):
        return _fail("health must not equate connecting to no liq")
    if hp.get("last_event_ago_min") is not None:
        return _fail("no events → null ago")

    os.environ["OFFICE_DB_PATH"] = "/tmp/pr38-no-such-office.db"
    from office_mini_app import build_live_state  # noqa: E402

    st = build_live_state(summary_events=[], watching_n=0)
    if "btc" not in st or "sessions" not in st:
        return _fail(f"state keys {st.keys()}")
    if st["market"]["greed_index"] is not None:
        return _fail("must not invent greed")
    if st["t7_status"] is not None and st["t7_status"] not in ("connected", "connecting", "disconnected"):
        return _fail(f"t7 {st['t7_status']}")
    if st["sessions"].get("active") is None:
        return _fail("session clock from time is allowed")

    card = format_opportunity_alert(
        symbol="DEMOUSDT",
        direction="SHORT",
        timeframe="H1",
        mode="intraday",
        entry=0.1306,
        sl=0.1321,
        tp1=0.1235,
        rr_net=4.8,
        move_pct=5.5,
    )
    if "Потенціал до TP1: 5.5%" not in card:
        return _fail(card)
    if "приблизно" in card.lower() or "не чистий" in card.lower():
        return _fail("approx")
    if "RR: 1:4.8" not in card:
        return _fail(f"rr {card}")
    if "RR після витрат" in card:
        return _fail("old rr")
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
                confirmation="x",
                cancel="",
            )
        ],
    )
    if level_book_to_alert(kaito) is not None:
        return _fail("kaito feed")
    print("OK: test_pr38_all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
