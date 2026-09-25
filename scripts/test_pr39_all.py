#!/usr/bin/env python3
"""PR39: свіп/вхід, D1/H1 логіка, Asian поточної доби, регресії T0–T8."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_btc_liquidations import MAX_RECONNECT_ATTEMPTS, reconnect_plan  # noqa: E402
from office_external_signal import ingest_external_signal, review_external_signal  # noqa: E402
from office_lifecycle import (  # noqa: E402
    db_status_for,
    format_sweep_approach_alert,
    format_waiting_sweep_watch,
    next_lifecycle_state,
    sweep_approach_due,
)
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_news_agent import DATA_UNAVAILABLE as NAZAR_UNAVAILABLE  # noqa: E402
from office_news_agent import format_nazar_update  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_telegram_filter import (  # noqa: E402
    MIN_ALERT_MOVE_PCT,
    alert_decision,
    format_opportunity_alert,
    level_book_to_alert,
    level_book_to_sweep_approach,
    level_book_to_watching,
    range_result_to_alert,
)
from office_topdown import (  # noqa: E402
    COUNTER_TREND_MIN_RR,
    DATA_UNAVAILABLE,
    ENTRY_WAITING_SWEEP,
    asian_session_range,
    entry_gate_from_topdown,
    structure_confluence,
    sweep_near,
    sweep_story,
)
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402

PENGU = """
📌 Сигнал бота · ПРЕМІУМ · СКАЛЬП
🟢 LONG · PENGUUSDT · 5m · #17
🕐 23:09 25.09.2026 · поза іменованою сесією · TREND
💰 Вхід:  0.010273 (50%)
🛑 SL:    0.00993793 (3.3%)
🎯 TP1:   0.0107756 (+4.9%)
"""


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
    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("order")
    if COUNTER_TREND_MIN_RR != 2.5:
        return _fail("counter rr")

    silent = format_nazar_update(data_status=NAZAR_UNAVAILABLE)
    if silent is not None:
        return _fail("nazar timeout")
    stuck = reconnect_plan(state="connecting", age_sec=301, attempt=2)
    if not stuck.get("reconnect") or stuck.get("means_no_liquidations"):
        return _fail(f"t7 {stuck}")
    if MAX_RECONNECT_ATTEMPTS != 10:
        return _fail("t7 attempts")

    asof = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    today_asia = []
    for h in range(0, 8):
        for m in (0, 15, 30, 45):
            ts = f"2026-09-25T{h:02d}:{m:02d}:00+00:00"
            hi = 0.0332 if (h, m) == (1, 0) else 0.0330
            lo = 0.0324 if (h, m) == (3, 0) else 0.0326
            today_asia.append(_c(0.0328, hi, lo, 0.032889, ts))
    yday = [_c(0.0400, 0.040989, 0.0390, 0.0405, f"2026-09-24T{h:02d}:00:00+00:00") for h in range(0, 8)]
    mixed = yday + today_asia
    asia = asian_session_range(mixed, asof=asof, current_price=0.032889)
    if asia.get("data_status") != "DATA_OK":
        return _fail(f"today asia {asia}")
    if abs(float(asia["high"]) - 0.0332) > 1e-9:
        return _fail(f"must ignore yesterday high {asia}")
    wild = asian_session_range(
        [_c(0.0328, 0.040989, 0.0324, 0.032889, f"2026-09-25T{h:02d}:00:00+00:00") for h in range(0, 8)],
        asof=asof,
        current_price=0.032889,
    )
    if wild.get("data_status") != DATA_UNAVAILABLE or wild.get("high") is not None:
        return _fail(f"15% guard {wild}")
    if "підозрілий" not in str(wild.get("note") or "") and wild.get("note") != DATA_UNAVAILABLE:
        if wild.get("data_status") != DATA_UNAVAILABLE:
            return _fail(f"note {wild}")
    short_asia = asian_session_range(
        [_c(0.03, 0.031, 0.029, 0.03, "2026-09-25T00:00:00+00:00"),
         _c(0.03, 0.031, 0.029, 0.03, "2026-09-25T00:15:00+00:00")],
        asof=asof,
        current_price=0.03,
    )
    if short_asia.get("high") is not None:
        return _fail("need 4 bars")

    ahead = sweep_story(
        [
            _c(0.0330, 0.0332, 0.0328, 0.0329, "2026-09-25T10:00:00+00:00"),
            _c(0.0329, 0.0331, 0.0327, 0.03285, "2026-09-25T10:05:00+00:00"),
            _c(0.03285, 0.0330, 0.03275, 0.032889, "2026-09-25T10:10:00+00:00"),
        ],
        direction="LONG",
    )
    if ahead.get("status") != "ще попереду" or ahead.get("entry_mode") != ENTRY_WAITING_SWEEP:
        return _fail(f"ahead {ahead}")
    if "SSL нижче" not in str(ahead.get("line") or ""):
        return _fail(f"ahead line {ahead}")
    gate = entry_gate_from_topdown(sweep=ahead, already_confirmed=True, rr_net=3.0)
    if gate.get("allow_signal") or gate.get("entry_mode") != ENTRY_WAITING_SWEEP:
        return _fail(f"gate {gate}")

    done = sweep_story(
        [
            _c(0.1304, 0.1308, 0.1300, 0.1305, "2026-09-25T21:00:00+00:00"),
            _c(0.1305, 0.1309, 0.1301, 0.1304, "2026-09-25T21:05:00+00:00"),
            _c(0.1304, 0.1312, 0.1300, 0.1302, "2026-09-25T21:14:00+00:00"),
        ],
        direction="SHORT",
    )
    if done.get("status") != "стався" or "BSL знято" not in str(done.get("line") or ""):
        return _fail(f"done {done}")
    if "00:14" not in str(done.get("line") or "") or "на рівні" not in str(done.get("line") or ""):
        return _fail(f"time/level {done}")
    g2 = entry_gate_from_topdown(sweep=done, already_confirmed=True, rr_net=3.0, confluence={})
    if not g2.get("allow_signal"):
        return _fail(f"done gate {g2}")

    watch = format_waiting_sweep_watch(
        symbol="AKEUSDT",
        timeframe="H1",
        direction="LONG",
        sweep_level=0.032122,
        sweep_kind="SSL",
    )
    if "👀 WATCHING · AKEUSDT · H1" not in watch:
        return _fail(watch)
    if "SSL sweep нижче 0.032122" not in watch:
        return _fail(watch)
    if db_status_for("WAITING_SWEEP") != "WATCHING":
        return _fail("db status")
    step = next_lifecycle_state(
        current="WAITING_SWEEP",
        price=0.032889,
        entry_low=0.032122,
        created_ts="2026-09-25T21:00:00+00:00",
        now_ts="2026-09-25T21:10:00+00:00",
        sweep_happened=False,
    )
    if step["state"] != "WAITING_SWEEP":
        return _fail(f"stay waiting {step}")
    if not sweep_near(price=0.032250, level=0.032122):
        return _fail("0.3% near")
    if sweep_near(price=0.0400, level=0.032122):
        return _fail("far not near")
    if not sweep_approach_due(price=0.032250, level=0.032122):
        return _fail("approach due")
    near_txt = format_sweep_approach_alert(
        symbol="AKEUSDT",
        level=0.032122,
        price=0.032250,
        direction="LONG",
    )
    if "наближається до зони свіпу" not in near_txt or "0.032122" not in near_txt:
        return _fail(near_txt)
    if "0.03225" not in near_txt:
        return _fail(near_txt)

    conf = structure_confluence(
        d1={"bias": "LONG", "label": "висхідний тренд (HH/HL)", "data_status": "DATA_OK"},
        h1={"bias": "SHORT", "label": "низхідний тренд (LH/LL)", "data_status": "DATA_OK"},
        direction="LONG",
    )
    if not conf.get("requires_m15_bos") or "D1 бичачий" not in str(conf.get("structure_line") or ""):
        return _fail(f"conflict {conf}")
    if "купуємо корекцію в D1 тренді після BOS на M15" not in str(conf.get("logic_line") or ""):
        return _fail(f"logic {conf}")
    bos_gate = entry_gate_from_topdown(
        sweep=done,
        confluence=conf,
        already_confirmed=True,
        rr_net=2.0,
        m15_bos=False,
        direction="LONG",
    )
    if bos_gate.get("allow_signal") or "BOS" not in str(bos_gate.get("reason") or ""):
        return _fail(f"bos required {bos_gate}")
    ctr = structure_confluence(
        d1={"bias": "SHORT", "label": "низхідний тренд (LH/LL)", "data_status": "DATA_OK"},
        h1={"bias": "LONG", "label": "висхідний тренд (HH/HL)", "data_status": "DATA_OK"},
    )
    if float(ctr.get("min_rr") or 0) != 2.5 or not ctr.get("requires_m15_bos"):
        return _fail(f"counter {ctr}")
    aligned = structure_confluence(
        d1={"bias": "SHORT", "label": "низхідний тренд (LH/LL)", "data_status": "DATA_OK"},
        h1={"bias": "SHORT", "label": "низхідний тренд (LH/LL)", "data_status": "DATA_OK"},
    )
    if aligned.get("conflict") or "збігаються" not in str(aligned.get("confluence_note") or ""):
        return _fail(f"aligned {aligned}")

    card = format_opportunity_alert(
        symbol="AKEUSDT",
        direction="LONG",
        timeframe="H1",
        entry=0.032889,
        sl=0.0319,
        tp1=0.0350,
        rr_net=2.2,
        move_pct=6.4,
        structure_line=conf["structure_line"],
        logic_line=conf["logic_line"],
        sweep_line=ahead["line"],
        mode="intraday",
        entry_mode=ENTRY_WAITING_SWEEP,
        sweep_level=0.032122,
    )
    if "Логіка: купуємо корекцію" not in card:
        return _fail(card)
    if "після свіпу" not in card:
        return _fail(f"entry wait {card}")

    ake_book = SimpleNamespace(
        symbol="AKEUSDT",
        mode="intraday",
        extras={
            "price": 0.032889,
            "topdown": {
                "entry_mode": ENTRY_WAITING_SWEEP,
                "logic_line": conf["logic_line"],
                "structure_line": conf["structure_line"],
                "sweep": ahead,
                "asia": {"high": None, "low": None},
            },
            "entry_mode": ENTRY_WAITING_SWEEP,
        },
        scenarios=[
            SimpleNamespace(
                status="WATCHING",
                direction="LONG",
                setup="bounce",
                entry=0.032889,
                sl=0.0319,
                tp1=0.0350,
                tp2=None,
                rr_net=4.0,
                confirmation="x",
                cancel="",
                entry_mode=ENTRY_WAITING_SWEEP,
            )
        ],
    )
    if level_book_to_alert(ake_book) is not None:
        return _fail("waiting must not be signal")
    wtxt = level_book_to_watching(ake_book)
    if wtxt is None or "WATCHING · AKEUSDT" not in wtxt:
        return _fail(f"watching card {wtxt}")
    ake_book.extras["price"] = 0.032250
    ahead_near = dict(ahead)
    ahead_near["level"] = 0.032122
    ake_book.extras["topdown"]["sweep"] = ahead_near
    atxt = level_book_to_sweep_approach(ake_book, price=0.032250)
    if atxt is None or "наближається" not in atxt:
        return _fail(f"approach {atxt}")

    done_book = SimpleNamespace(
        symbol="DEMOUSDT",
        mode="intraday",
        extras={
            "price": 0.1306,
            "topdown": {
                "entry_mode": "CONFIRMED_ENTRY",
                "structure_line": "D1 низхідний тренд (LH/LL) · H1 низхідний тренд (LH/LL)",
                "logic_line": "",
                "sweep": done,
                "asia": {"high": 0.1315, "low": 0.1298},
            },
        },
        scenarios=[
            SimpleNamespace(
                status="CONFIRMED",
                direction="SHORT",
                setup="bounce",
                entry=0.1306,
                sl=0.1321,
                tp1=0.1235,
                tp2=None,
                rr_net=4.8,
                confirmation="x",
                cancel="",
                entry_mode="CONFIRMED_ENTRY",
            )
        ],
    )
    sig = level_book_to_alert(done_book)
    if sig is None or "BSL знято" not in sig or "на рівні" not in sig:
        return _fail(f"signal {sig}")

    orig = ingest_external_signal(text=PENGU, msg_id=17, received_at="2026-09-25T20:53:00+00:00")
    rev = review_external_signal(
        orig,
        market={
            "price": 0.010111,
            "day_used_pct": 120.7,
            "edge_score": 65,
            "m15_ok": False,
            "structure_sl": 0.00993793,
            "review_at": "2026-09-25T20:53:00+00:00",
            "quote_asof": "2026-09-25T20:53:00+00:00",
            "data_status": "DATA_OK",
        },
    )
    if not (rev.extras or {}).get("signal_stale"):
        return _fail("pengu stale")
    if rev.office_plan is not None:
        return _fail("stale copy")
    reasons = " ".join(rev.reasons)
    if "23:09" not in reasons or "23:53" not in reasons:
        return _fail(reasons)
    if rev.opens_position:
        return _fail("review is not position")

    kaito = alert_decision(status="CONFIRMED", entry=0.3559, sl=0.35660885, tp1=0.35312, rr_net=3.01)
    if kaito["send"]:
        return _fail("kaito")
    wait_dec = alert_decision(
        status="CONFIRMED",
        entry=0.032889,
        sl=0.0319,
        tp1=0.0350,
        rr_net=4.0,
        entry_mode=ENTRY_WAITING_SWEEP,
    )
    if wait_dec["send"]:
        return _fail("waiting in feed")
    silent_rng = SimpleNamespace(status="RANGE_WATCHING", card=None, symbol="BTCUSDT", event="INSIDE")
    if range_result_to_alert(silent_rng) is not None:
        return _fail("inside")

    print("OK: test_pr39_all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
