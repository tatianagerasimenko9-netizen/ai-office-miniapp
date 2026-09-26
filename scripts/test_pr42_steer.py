#!/usr/bin/env python3
"""PR42: стоп за маніпуляцією, тригер, один re-entry, ведення, журнал ≠ /position."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_bridge import (  # noqa: E402
    OFFICE_SIGNAL_REASON,
    build_olesya_evening_debrief,
    init_office_db,
    is_confirmed_position_row,
    journal_close_trade,
    journal_open_office_signal,
    journal_update_excursions,
    office_signal_trade_id,
)
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR, evaluate_radar, format_radar_card  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_telegram_filter import MIN_ALERT_MOVE_PCT  # noqa: E402
from office_telegram_policy import (  # noqa: E402
    EVENT_SIGNAL_ENTRY,
    EVENT_TRADE_CLOSED,
    EVENT_TRADE_UPDATE,
    PROACTIVE_ALLOWED,
    may_send_proactive,
)
from office_trade_steer import (  # noqa: E402
    RR_TIGHT_FLAG,
    SL_ATR_MULT,
    SCALE_ADD2_PCT,
    SCALE_ADD_PCT,
    SCALE_ENTRY_PCT,
    ManageBook,
    encode_sc_zone_note,
    format_entry_trigger,
    format_signal_steer_card,
    plan_stop_behind_manipulation,
    plan_strong_candle_ote,
    plan_sweep_reentry,
    parse_sc_zone_note,
    replay_manage,
    sc_setup_cancelled,
    signal_case_key,
    tp3_from_liquidity,
)
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402

ART = Path("/opt/cursor/artifacts")


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl, ts="") -> dict:
    return {"open": o, "high": h, "low": l, "close": cl, "ts": ts}


def _longxia_m15() -> list:
    rows = []
    for i in range(10):
        rows.append(_c(0.1306, 0.1310, 0.1305, 0.1307, f"c{i}"))
    rows.append(_c(0.1307, 0.1325, 0.1306, 0.1308, "sweep"))
    for i in range(4):
        rows.append(_c(0.1307, 0.1310, 0.1304, 0.1306, f"a{i}"))
    # Сильна червона свічка ~0.130–0.133 (як на індикаторі Тетяни).
    rows.append(_c(0.1330, 0.1330, 0.1300, 0.13005, "sc"))
    return rows


def _ake_path() -> list:
    rows = []
    rows.append(_c(0.0329, 0.0330, 0.0325, 0.0328, "e0"))
    rows.append(_c(0.0328, 0.0329, 0.0322, 0.0326, "sweep-low"))
    for i in range(4):
        rows.append(_c(0.0327, 0.0332, 0.0326, 0.0331, f"up{i}"))
    rows.append(_c(0.0331, 0.0348, 0.0330, 0.03475, "tp1"))
    rows.append(_c(0.0348, 0.0354, 0.0347, 0.03530, "tp2"))
    rows.append(_c(0.0353, 0.0360, 0.0351, 0.0358, "trail1"))
    rows.append(_c(0.0358, 0.0375, 0.0357, 0.0374, "peak"))
    rows.append(_c(0.0374, 0.0375, 0.0350, 0.0351, "break"))
    rows.append(_c(0.0351, 0.0352, 0.0322, 0.0323, "giveback"))
    return rows


def _fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    try:
        qs = urlencode(
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1500,
            }
        )
        req = Request(
            f"https://fapi.binance.com/fapi/v1/klines?{qs}",
            headers={"User-Agent": "ai-office-pr42", "Accept": "application/json"},
        )
        with urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        out = []
        if not isinstance(data, list):
            return []
        for row in data:
            if not isinstance(row, list) or len(row) < 6:
                continue
            ts = datetime.fromtimestamp(int(row[0]) / 1000.0, tz=timezone.utc).isoformat()
            out.append(
                {
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "ts": ts,
                }
            )
        return out
    except Exception as exc:
        print(f"DATA_UNAVAILABLE {symbol} {interval}: {type(exc).__name__}: {exc}")
        return []


def main() -> int:
    print(
        "KNOWLEDGE: OFFICE_AGENT_SYSTEM_PROMPTS_UA.md (відкат до сильної свічки); "
        "office_worker_library/shared/SMC_ANALIZ_SNAPSHOT.md OTE 0.62-0.79; "
        "SMART_MANY_KONSEPT_SNAPSHOT.md §0.13.1; "
        "STATISTYKA_SNAPSHOT.txt вхід 70%/добір 20%; "
        "office_topdown.last_impulse_candle; fetch_ote_levels 0.618/0.705/0.786; "
        "ARKHITEKTURA ENTRY_CONFIRMATION_MODE=SC_OR_ENTRY; "
        "Pine ICT SMC HUNTER v9.9 — немає в репо"
    )
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("atr frozen")
    if SIGNAL_THRESHOLD != 85 or MIN_ALERT_MOVE_PCT != 3.0 or MIN_RR < 1.5:
        return _fail("edge/3%/rr frozen")
    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("order")
    if EVENT_SIGNAL_ENTRY not in PROACTIVE_ALLOWED:
        return _fail("policy")
    if not may_send_proactive(EVENT_TRADE_UPDATE) or not may_send_proactive(EVENT_TRADE_CLOSED):
        return _fail("trade events")

    trig = format_entry_trigger(direction="SHORT", tf="M15", level=0.1305, entry=0.1306)
    if "M15" not in trig or "нижче" not in trig or "0.1305" not in trig:
        return _fail(f"trigger {trig}")
    card = format_signal_steer_card(
        symbol="LONGXIAUSDT",
        direction="SHORT",
        timeframe="H1",
        entry=0.1306,
        sl=0.1327,
        tp1=0.12345,
        tp2=0.098,
        trigger=trig,
        reentry=True,
        sweep_note="Стоп вибило свіпом до 0.1325 — ціна повернулась нижче 0.1310",
    )
    if "ПОВТОРНИЙ SHORT" not in card or "перевірте" in card.lower():
        return _fail("reentry card")

    m15 = _longxia_m15()
    planned = plan_stop_behind_manipulation(
        entry=0.13063,
        tp1=0.12345,
        direction="SHORT",
        candles_m15=m15,
        current_sl=0.130986,
    )
    if not planned.get("send") or planned.get("sl") is None:
        return _fail(f"longxia plan {planned}")
    if float(planned["sl"]) < 0.1325:
        return _fail(f"sl not behind sweep {planned['sl']}")
    if float(planned["sl"]) <= 0.1330:
        return _fail(f"sl must be above SC high 0.133 {planned['sl']}")
    tight_rr = abs(0.12345 - 0.13063) / abs(0.13063 - 0.130986)
    if tight_rr <= RR_TIGHT_FLAG:
        return _fail("fixture rr")
    if float(planned["rr"]) + 1e-12 < MIN_RR:
        return _fail("rr after widen")

    tiny = [_c(1.0, 1.001, 0.999, 1.0, str(i)) for i in range(8)]
    atr_plan = plan_stop_behind_manipulation(
        entry=1.0,
        tp1=0.97,
        direction="SHORT",
        candles_m15=tiny,
        atr_m15=0.02,
    )
    if atr_plan.get("sl") is None:
        return _fail("atr sl")
    if abs(1.0 - float(atr_plan["sl"])) + 1e-12 < SL_ATR_MULT * 0.02:
        return _fail(f"atr floor {atr_plan}")

    skip = plan_stop_behind_manipulation(
        entry=0.13063,
        tp1=0.13050,
        direction="SHORT",
        candles_m15=m15,
        current_sl=0.130986,
    )
    if skip.get("send"):
        return _fail("must skip tiny TP1 after wide SL")

    none = plan_stop_behind_manipulation(
        entry=0.13,
        tp1=0.12,
        direction="SHORT",
        candles_m15=[],
    )
    if none.get("data_status") != "DATA_UNAVAILABLE" or none.get("sl") is not None:
        return _fail("no invent sl")

    ck = signal_case_key(symbol="LONGXIAUSDT", direction="SHORT", timeframe="H1", day="2026-09-26")
    sweep_c = _c(0.1307, 0.1325, 0.1304, 0.1308)
    r1 = plan_sweep_reentry(
        case_key=ck,
        already_reentered=False,
        direction="SHORT",
        sl=0.130986,
        reclaim_level=0.1310,
        last_candle=sweep_c,
        candles_h1=m15,
        wick_extreme=0.1325,
    )
    if not r1.get("allow"):
        return _fail(f"reentry {r1}")
    r2 = plan_sweep_reentry(
        case_key=ck,
        already_reentered=True,
        direction="SHORT",
        sl=0.130986,
        reclaim_level=0.1310,
        last_candle=sweep_c,
    )
    if r2.get("allow"):
        return _fail("second reentry")

    sc = plan_strong_candle_ote(direction="SHORT", candles=m15, price=0.13063)
    if sc.get("data_status") != "DATA_OK":
        return _fail(f"sc {sc}")
    if float(sc["high"]) < 0.1329 or float(sc["low"]) > 0.1301:
        return _fail(f"sc zone {sc['low']}-{sc['high']}")
    pcts = [int(b["pct"]) for b in sc["buckets"]]
    if pcts != [SCALE_ENTRY_PCT, SCALE_ADD_PCT, SCALE_ADD2_PCT]:
        return _fail(f"buckets {pcts}")
    if sc_setup_cancelled(direction="SHORT", close=0.1325, sc_low=sc["low"], sc_high=sc["high"]):
        return _fail("0.1325 inside SC is not cancel")
    if not sc_setup_cancelled(direction="SHORT", close=0.1335, sc_low=sc["low"], sc_high=sc["high"]):
        return _fail("close above SC must cancel")
    note = f"radar SIGNAL {encode_sc_zone_note(sc)}"
    parsed = parse_sc_zone_note(note)
    if not parsed:
        return _fail("parse sc note")

    # Екран ICT SMC HUNTER: H4 HIGH 0.10952, Відкат SC (OTE) 0.10156–0.10328.
    hunter = [_c(0.0994, 0.10952, 0.0994, 0.10952, "bull-sc")]
    long_sc = plan_strong_candle_ote(direction="LONG", candles=hunter, price=0.104)
    if long_sc.get("data_status") != "DATA_OK":
        return _fail("hunter sc")
    if abs(float(long_sc["ote_hi"]) - 0.10328) > 0.0004:
        return _fail(f"hunter ote hi {long_sc['ote_hi']}")
    if abs(float(long_sc["ote_lo"]) - 0.10156) > 0.0004:
        return _fail(f"hunter ote lo {long_sc['ote_lo']}")

    txt_sc = format_signal_steer_card(
        symbol="LONGXIAUSDT",
        direction="SHORT",
        timeframe="H1",
        entry=0.1306,
        sl=planned["sl"],
        tp1=0.12345,
        trigger=trig,
        sc_plan=sc,
    )
    if "OTE 62–79%" not in txt_sc or "70%" not in txt_sc or "Скасовано" not in txt_sc:
        return _fail(f"sc card {txt_sc}")

    # Широкий стоп не вибивається свіпом 0.1325.
    book_lx = ManageBook(
        symbol="LONGXIAUSDT",
        direction="SHORT",
        entry=0.13063,
        sl=float(planned["sl"]),
        tp1=0.12345,
        tp2=0.098,
    )
    ev_lx = replay_manage(book_lx, m15 + [_c(0.1306, 0.1325, 0.120, 0.122, "tp1bar")])
    kinds_lx = [e["kind"] for e in ev_lx]
    if "SL" in kinds_lx:
        return _fail(f"wide sl should survive sweep {ev_lx}")
    if "TP1" not in kinds_lx:
        return _fail(f"longxia tp1 {ev_lx}")

    daily = [_c(0.032, 0.0378, 0.0318, 0.033, "yday"), _c(0.033, 0.034, 0.032, 0.033, "today")]
    t3 = tp3_from_liquidity(direction="LONG", daily_candles=daily)
    if t3 is None or t3 < 0.037:
        return _fail(f"tp3 {t3}")
    book_ake = ManageBook(
        symbol="AKEUSDT",
        direction="LONG",
        entry=0.032889,
        sl=0.032151,
        tp1=0.034746,
        tp2=0.035287,
        tp3=float(t3),
    )
    path = _ake_path()
    ev_ake = replay_manage(book_ake, path)
    kinds_ake = [e["kind"] for e in ev_ake]
    if kinds_ake[0] != "TP1" or "TP2" not in kinds_ake:
        return _fail(f"ake kinds {kinds_ake}")
    if not any(k in kinds_ake for k in ("TRAIL", "TP3", "REVERSAL", "SL", "HOLD")):
        return _fail(f"ake no trail/fix {kinds_ake}")
    if "SL" not in kinds_ake and "REVERSAL" not in kinds_ake and "TP3" not in kinds_ake:
        return _fail(f"ake must close before giveback {kinds_ake}")
    if book_ake.mfe < 10.0:
        return _fail(f"ake mfe {book_ake.mfe}")
    dup = replay_manage(book_ake, path)
    if dup:
        return _fail("closed book must stay silent")
    # Другий прохід порожньої книги з ACTIVE — spam check на HOLD
    book2 = ManageBook(
        symbol="AKEUSDT",
        direction="LONG",
        entry=0.032889,
        sl=0.032151,
        tp1=0.034746,
        tp2=0.035287,
        state="TP2",
        trail_sl=0.034746,
        last_event="HOLD",
    )
    hold_bars = [
        _c(0.0355, 0.0356, 0.0353, 0.03555, "h1"),
        _c(0.0355, 0.0357, 0.0354, 0.0356, "h2"),
        _c(0.0356, 0.0358, 0.0354, 0.0352, "h3"),
    ]
    from office_trade_steer import next_manage_event

    e1 = next_manage_event(book2, price=0.03555, candles_m15=hold_bars[:2])
    e2 = next_manage_event(book2, price=0.0356, candles_m15=hold_bars[:2])
    if e2 is not None and e1 is not None and e1.get("kind") == "HOLD" and e2.get("kind") == "HOLD":
        return _fail("hold spam")

    db = str(Path(tempfile.mkdtemp()) / "pr42.db")
    init_office_db(db)
    tid = journal_open_office_signal(
        db,
        signal_id="longxia-1",
        symbol="LONGXIAUSDT",
        direction="SHORT",
        entry_price=0.13063,
        stop_loss=float(planned["sl"]),
        take_profit=0.12345,
        tp2=0.098,
        timeframe="H1",
        setup_note="TEST",
    )
    if tid != office_signal_trade_id("longxia-1"):
        return _fail("tid")
    if is_confirmed_position_row(OFFICE_SIGNAL_REASON, "OFFICE_SIGNAL", tid):
        return _fail("signal != position")
    journal_update_excursions(db, trade_id=tid, mfe_pct=25.0, mae_pct=1.2, extra={"result": "TP1"})
    journal_close_trade(
        db,
        trade_id=tid,
        outcome="WIN",
        exit_price=0.12345,
        pnl_pct=5.0,
        exit_reason="TP1",
        context_patch={"result": "TP1", "mfe_pct": 25.0, "mae_pct": 1.2},
    )
    now = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
    debrief = build_olesya_evening_debrief(db, now=now)
    if debrief:
        return _fail(f"olesya must ignore office signal {debrief!r}")

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
    txt = format_radar_card(ok)
    if "Entry:" not in txt:
        return _fail("radar card")

    start_ms = int(datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
    live_rows = []
    for sym, side, entry, sl0, tp1, tp2 in (
        ("LONGXIAUSDT", "SHORT", 0.13063, 0.130986, 0.12345, 0.098),
        ("AKEUSDT", "LONG", 0.032889, 0.032151, 0.034746, 0.035287),
    ):
        bars = _fetch_klines(sym, "15m", start_ms, end_ms)
        if not bars:
            live_rows.append((sym, "DATA_UNAVAILABLE", [], None))
            continue
        pl = plan_stop_behind_manipulation(
            entry=entry,
            tp1=tp1,
            direction=side,
            candles_m15=bars[: max(8, min(len(bars), 24))],
            current_sl=sl0,
        )
        sl_use = float(pl["sl"]) if pl.get("send") and pl.get("sl") is not None else sl0
        t3v = tp3_from_liquidity(direction=side, daily_candles=_fetch_klines(sym, "1d", start_ms, end_ms))
        b = ManageBook(symbol=sym, direction=side, entry=entry, sl=sl_use, tp1=tp1, tp2=tp2, tp3=t3v)
        evs = replay_manage(b, bars)
        live_rows.append((sym, "OK", evs, sl_use))

    ART.mkdir(parents=True, exist_ok=True)
    lines = ["# PR42 replay", ""]
    lines.append("| час | монета | подія | текст |")
    lines.append("|---|---|---|---|")
    lines.append(f"| synth | LONGXIAUSDT | SL | {planned['sl']:.6f} за зоною (якір {planned.get('anchor')}) |")
    for e in ev_lx:
        lines.append(f"| {e.get('ts')} | LONGXIAUSDT | {e.get('kind')} | {e.get('message')} |")
    for e in ev_ake:
        lines.append(f"| {e.get('ts')} | AKEUSDT | {e.get('kind')} | {e.get('message')} |")
    for sym, st, evs, sl_use in live_rows:
        lines.append(f"| live | {sym} | {st} | sl={sl_use} events={len(evs)} |")
        for e in evs:
            lines.append(f"| {e.get('ts')} | {sym} | {e.get('kind')} | {e.get('message')} |")
    (ART / "pr42_replay.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("OK: test_pr42_steer")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
