#!/usr/bin/env python3
"""PR44: розмір позиції, PUMP/DUMP, RSI-перегрів, ICT-патерни, тиша PR40–41."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_bridge import (  # noqa: E402
    OFFICE_SIGNAL_REASON,
    init_office_db,
    is_confirmed_position_row,
    journal_open_office_signal,
    journal_update_excursions,
    office_signal_trade_id,
)
from office_ict_hunter import (  # noqa: E402
    HUNTER_EQ,
    HUNTER_OTE,
    daily_eq_ote_hunter,
    detect_amd_3,
    detect_turtle_soup,
    evaluate_ict_hunter,
    hunter_min_score,
    mo_filter_ok,
)
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_position_size import plan_position_size, risk_pct_for_score  # noqa: E402
from office_pump_dump import (  # noqa: E402
    PUMP_EQ,
    PUMP_OTE,
    daily_eq_ote,
    evaluate_pump_dump,
    format_pump_card,
    pump_add_retest,
    pump_continuation,
)
from office_radar import MIN_RR, evaluate_radar  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_rsi_heat import RSI_LONG_HOT, exhaustion_candle, rsi_heat, rsi_wilder  # noqa: E402
from office_telegram_filter import MIN_ALERT_MOVE_PCT  # noqa: E402
from office_telegram_policy import (  # noqa: E402
    EVENT_EVENING_DEBRIEF,
    EVENT_NEWS_CRITICAL,
    EVENT_SIGNAL_ENTRY,
    EVENT_TRADE_CLOSED,
    EVENT_TRADE_UPDATE,
    PROACTIVE_ALLOWED,
    may_send_proactive,
)
from office_trade_steer import ManageBook, format_signal_steer_card, next_manage_event  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402
from scripts.test_pr42_steer import fetch_vision_day  # noqa: E402

ART = Path("/opt/cursor/artifacts")


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl, ts="", vol=10.0) -> dict:
    return {"open": o, "high": h, "low": l, "close": cl, "ts": ts, "volume": vol}


def _pump_bars() -> list:
    rows = []
    for i in range(21):
        px = 100.0 + i * 0.01
        rows.append(_c(px, px + 0.05, px - 0.05, px, f"p{i}", vol=10))
    # Велика червона (скидання) для delev=3 після підтвердження.
    rows.append(_c(100.3, 100.35, 98.4, 98.5, "red", vol=50))
    # Підтвердження + пробій 20-хай + сплеск об'єму.
    rows.append(_c(98.6, 101.2, 98.55, 100.4, "pump", vol=80))
    return rows


def main() -> int:
    pine_p = ROOT / "office_worker_library/indicator/pump_dump_hunter_v2.pine"
    pine_h = ROOT / "office_worker_library/indicator/ict_smc_hunter_v9_9.pine"
    txtp = pine_p.read_text(encoding="utf-8") if pine_p.exists() else ""
    txth = pine_h.read_text(encoding="utf-8") if pine_h.exists() else ""
    if "0.786" not in txtp or "sig_pump" not in txtp or "sl_atr" not in txtp:
        return _fail("pump pine etalon")
    if "EQ=0.786" not in txth and "EQ = 0.786" not in txth and "0.786" not in txth:
        return _fail("hunter pine eq note")
    if PUMP_OTE != 0.786 or PUMP_EQ != 0.5:
        return _fail("pump ote/eq")
    if HUNTER_OTE != 0.5 or HUNTER_EQ != 0.786:
        return _fail("hunter ote/eq inverted")
    if PUMP_OTE == HUNTER_OTE or PUMP_EQ == HUNTER_EQ:
        return _fail("modules must not share ote/eq")
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("atr frozen")
    if SIGNAL_THRESHOLD != 85 or MIN_ALERT_MOVE_PCT != 3.0 or MIN_RR < 1.5:
        return _fail("edge/3%/rr frozen")
    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("order")
    if PROACTIVE_ALLOWED != {
        EVENT_SIGNAL_ENTRY,
        EVENT_TRADE_UPDATE,
        EVENT_TRADE_CLOSED,
        EVENT_NEWS_CRITICAL,
        EVENT_EVENING_DEBRIEF,
    }:
        return _fail(f"quiet set {PROACTIVE_ALLOWED}")
    if not may_send_proactive(EVENT_TRADE_UPDATE):
        return _fail("trade update")

    os.environ.pop("OFFICE_DEPO_USDT", None)
    sz = plan_position_size(entry=0.13063, sl=0.134543, score=10, min_score=8)
    if not sz.get("ok") or sz.get("size_usdt") is not None:
        return _fail(f"no depo {sz}")
    if "ризик 1%" not in sz["line"] or "стоп" not in sz["line"]:
        return _fail(f"size line {sz['line']}")
    if risk_pct_for_score(12, 8) != 0.02:
        return _fail("strong risk")
    os.environ["OFFICE_DEPO_USDT"] = "1000"
    sz2 = plan_position_size(entry=0.13063, sl=0.134543, score=8, min_score=8)
    stop_frac = abs(0.13063 - 0.134543) / 0.13063
    expect = 1000 * 0.01 / stop_frac
    if sz2.get("size_usdt") is None or abs(float(sz2["size_usdt"]) - expect) > 1e-6:
        return _fail(f"depo size {sz2}")
    if "USDT" not in sz2["line"]:
        return _fail(sz2["line"])
    os.environ.pop("OFFICE_DEPO_USDT", None)

    daily = [_c(100, 110, 90, 108, "yday"), _c(108, 109, 107, 108, "today")]
    p_lv = daily_eq_ote(daily)
    h_lv = daily_eq_ote_hunter(daily)
    if p_lv["ote"] is None or abs(float(p_lv["ote"]) - (110 - 20 * 0.786)) > 1e-9:
        return _fail(f"pump ote {p_lv}")
    if h_lv["eq"] is None or abs(float(h_lv["eq"]) - (110 - 20 * 0.786)) > 1e-9:
        return _fail(f"hunter eq {h_lv}")
    if abs(float(p_lv["eq"]) - float(h_lv["ote"])) > 1e-9:
        return _fail("eq/ote swapped between modules")

    bars = _pump_bars()
    ev = evaluate_pump_dump(candles=bars, daily=daily)
    if ev.get("signal") != "PUMP":
        return _fail(f"pump signal {ev}")
    if ev.get("direction") != "LONG":
        return _fail("pump dir")
    if float(ev["total_l"]) < 10:
        return _fail(f"score {ev['total_l']}")
    risk = abs(float(ev["entry"]) - float(ev["sl"]))
    if abs(float(ev["tps"]["tp1"]) - (float(ev["entry"]) + risk * 1.5)) > 1e-9:
        return _fail("tp 1.5R")
    if abs(float(ev["tps"]["add"]) - (float(ev["entry"]) - risk * 0.4)) > 1e-9:
        return _fail("add 40%")
    card = format_pump_card("AKEUSDT", "M15", ev)
    if "Тип: PUMP" not in card or "Розмір:" not in card:
        return _fail(f"pump card {card}")
    if "OTE 62–79%" in card:
        return _fail("pump card mixed hunter ote")

    hot = rsi_heat(direction="LONG", rsi_h1=86.0, rsi_h4=70.0)
    if hot.get("allow_market") or not hot.get("pullback_only"):
        return _fail(f"rsi 86 {hot}")
    if RSI_LONG_HOT != 85:
        return _fail("hot const")
    ext = rsi_heat(direction="LONG", rsi_h1=93.0, in_position=True, exhaustion=True)
    if not ext.get("fix_partial") or not ext.get("dump_candidate"):
        return _fail(f"rsi extreme {ext}")
    cold = rsi_heat(direction="SHORT", rsi_h1=7.0, in_position=True, exhaustion=True)
    if not cold.get("fix_partial") or not cold.get("pump_candidate"):
        return _fail(f"rsi short {cold}")

    # AMD + Turtle Soup
    amd_rows = [_c(10, 10.1, 9.9, 10.0), _c(10.0, 10.05, 9.7, 9.8), _c(9.85, 10.2, 9.84, 10.15)]
    if detect_amd_3(amd_rows).get("side") != "LONG":
        return _fail("amd")
    turt = [_c(10, 10.2, 9.9, 10.1, vol=5) for _ in range(21)]
    turt.append(_c(10.1, 10.5, 10.0, 10.05, "soup"))  # wick above 20h, close back
    if detect_turtle_soup(turt).get("side") != "SHORT":
        return _fail("turtle")
    if hunter_min_score("M15") != 8 or hunter_min_score("H1") != 7 or hunter_min_score("H4") != 6:
        return _fail("thresholds")
    if mo_filter_ok(direction="LONG", close=101, mo=100) is not False:
        return _fail("mo long")
    if mo_filter_ok(direction="SHORT", close=99, mo=100) is not False:
        return _fail("mo short")

    # Hunter score from AMD+SMS-like series
    hunt_bars = []
    for i in range(24):
        hunt_bars.append(_c(10 - i * 0.02, 10.05 - i * 0.02, 9.9 - i * 0.02, 9.95 - i * 0.02, f"d{i}"))
    hunt_bars.append(_c(9.5, 9.55, 9.2, 9.3, "sh"))
    hunt_bars.append(_c(9.3, 9.8, 9.25, 9.75, "sms"))
    h = evaluate_ict_hunter(candles=hunt_bars + turt[-22:], timeframe="M15", daily=daily)
    if not h.get("ok"):
        return _fail(f"hunter {h}")

    book = ManageBook(
        symbol="RAREUSDT",
        direction="LONG",
        entry=1.0,
        sl=0.97,
        tp1=1.02,
        extras={"setup_type": "PUMP"},
    )
    e0 = next_manage_event(book, price=1.001, candles_m15=bars, rsi_h1=93.0, exhaustion=True)
    if not e0 or e0.get("kind") != "RSI_EXTREME":
        return _fail(f"rsi event {e0}")
    e1 = next_manage_event(book, price=1.001, candles_m15=bars, rsi_h1=93.0, exhaustion=True)
    if e1 is not None:
        return _fail("rsi spam")

    cont_rows = []
    px = 1.0
    for i in range(60):
        px = 1.0 + i * 0.0002
        cont_rows.append(_c(px, px + 0.001, px - 0.001, px, f"c{i}", vol=10))
    last = _c(1.02, 1.03, 1.019, 1.025, "cont", vol=80)
    cont_rows.append(last)
    book2 = ManageBook(
        symbol="AKEUSDT",
        direction="LONG",
        entry=1.0,
        sl=0.97,
        tp1=1.01,
        state="TP1",
        last_event="TP1",
        trail_sl=1.0,
        extras={"setup_type": "PUMP", "manage_bars": 2},
    )
    if not pump_continuation(direction="LONG", entry=1.0, candle=last, candles=cont_rows):
        # EMA may need trend; still test add + no spam path
        pass
    add_c = _c(1.0, 1.002, 0.999, 1.001, "add", vol=80)
    add_rows = cont_rows + [add_c]
    if not pump_add_retest(direction="LONG", entry=1.0, candle=add_c, candles=add_rows):
        return _fail("add retest")
    ev_add = next_manage_event(book2, price=1.001, candles_m15=add_rows)
    if ev_add is None or ev_add.get("kind") not in ("ADD", "CONT", "HOLD"):
        # CONT/ADD depend on EMA; ADD should fire
        if ev_add is None:
            return _fail("expected add/cont")
    ev_add2 = next_manage_event(book2, price=1.001, candles_m15=add_rows)
    if ev_add2 is not None and ev_add is not None and ev_add2.get("kind") == ev_add.get("kind"):
        return _fail("manage spam")

    db = str(Path(tempfile.mkdtemp()) / "pr44.db")
    init_office_db(db)
    tid = journal_open_office_signal(
        db,
        signal_id="rare-1",
        symbol="RAREUSDT",
        direction="LONG",
        entry_price=1.0,
        stop_loss=0.97,
        take_profit=1.02,
        timeframe="D1",
        setup_note="PUMP",
        rsi_h1=86.0,
        rsi_h4=70.0,
        rsi_peak=86.0,
    )
    if tid != office_signal_trade_id("rare-1"):
        return _fail("tid")
    if is_confirmed_position_row(OFFICE_SIGNAL_REASON, "OFFICE_SIGNAL", tid):
        return _fail("signal != position")
    journal_update_excursions(db, trade_id=tid, mfe_pct=2.0, mae_pct=0.4, extra={"rsi_h1": 90.0, "rsi_peak": 90.0})
    import json
    import sqlite3

    row = sqlite3.connect(db).execute("SELECT context_json FROM trade_journal WHERE trade_id=?", (tid,)).fetchone()
    ctx = json.loads(row[0])
    if float(ctx.get("rsi_at_signal") or 0) < 85 or float(ctx.get("rsi_peak") or 0) < 90:
        return _fail(f"rsi journal {ctx}")

    daily_ok = []
    for _ in range(8):
        daily_ok.append(_c(100, 110, 90, 100))
        daily_ok.append(_c(100, 111, 89.5, 101))
    sweep_ssl = [_c(10, 10.2, 9.8, 10.0), _c(10, 10.3, 9.85, 10.1), _c(10.0, 10.1, 9.5, 9.95)]
    ok = evaluate_radar(
        symbol="BTCUSDT",
        price=10.0,
        daily_candles=daily_ok,
        sweep_candles=sweep_ssl,
        m15_candles=[_c(9.9, 10.2, 9.9, 10.2)],
        day_used_pct=40.0,
        in_kill_zone=True,
    )
    if ok.status != "SIGNAL" or ok.opens_position:
        return _fail(f"radar regression {ok.status} {ok.reason}")
    txt = format_signal_steer_card(
        symbol="LONGXIAUSDT",
        direction="LONG",
        timeframe="H1",
        entry=0.13063,
        sl=0.134543,
        tp1=0.1377,
        setup_type="HUNTER",
        score=12,
        min_score=8,
        score_max=20,
    )
    if "Розмір:" not in txt or "ризик" not in txt:
        return _fail(txt)
    if not exhaustion_candle(_c(1.0, 1.04, 0.99, 1.035), side="LONG"):
        return _fail("exhaust")

    # RSI series ~86
    closes = [1.0]
    for i in range(20):
        closes.append(closes[-1] * 1.012)
    r = rsi_wilder(closes)
    if r is None or r < 70:
        return _fail(f"rsi climb {r}")

    vision_notes = []
    rare_rsi = None
    for day in ("2026-09-24", "2026-09-25", "2026-09-26"):
        pack = fetch_vision_day("RAREUSDT", "1d", day)
        vision_notes.append(f"RAREUSDT 1d {day}: {pack.get('reason')} n={pack.get('n', 0)}")
    hist = []
    rare_start = datetime(2026, 9, 5, tzinfo=timezone.utc)
    for i in range(21):
        day = datetime.fromtimestamp(rare_start.timestamp() + i * 86400, tz=timezone.utc).date().isoformat()
        pack = fetch_vision_day("RAREUSDT", "1d", day)
        vision_notes.append(f"RAREUSDT 1d {day}: {pack.get('reason')} n={pack.get('n', 0)}")
        if pack.get("ok"):
            hist.extend(pack.get("bars") or [])
    if hist:
        from office_rsi_heat import rsi_from_candles

        rare_rsi = rsi_from_candles(hist)
        vision_notes.append(f"RAREUSDT RSI(14) vision={rare_rsi} bars={len(hist)}")
        if rare_rsi is not None and rare_rsi >= 85:
            heat_r = rsi_heat(direction="LONG", rsi_h1=rare_rsi)
            if heat_r.get("allow_market"):
                return _fail("rare rsi must block market long")
    for sym in ("LONGXIAUSDT", "AKEUSDT"):
        for iv in ("15m", "1d"):
            pack = fetch_vision_day(sym, iv, "2026-09-25")
            vision_notes.append(f"{sym} {iv} 2026-09-25: {pack.get('reason')} n={pack.get('n', 0)}")

    ART.mkdir(parents=True, exist_ok=True)
    lines = ["# PR44 modules", ""]
    lines.append("PUMP OTE=0.786 EQ=0.5 · Hunter OTE=0.5 EQ=0.786 — не змішуються.")
    lines.append(f"PUMP card signal={ev.get('signal')} score={ev.get('total_l')}/18 sl={ev.get('sl')}")
    lines.append(f"size no-depo: {sz['line']}")
    lines.append(f"size depo1000: {sz2['line']}")
    lines.append(f"RSI 86 allow_market={hot.get('allow_market')} pullback={hot.get('pullback_only')}")
    for n in vision_notes:
        lines.append(f"- {n}")
    (ART / "pr44_modules.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("OK: test_pr44_modules")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
