"""B&R live observational Telegram stream. Paper outcomes only; NEVER submits orders.

Independent from Office2 READY/risk gates. Binance Futures CLOSED M15 for signals,
CLOSED M1 for outcomes. Separate BR-* IDs and durable DB state.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any, Callable

from office_br import card, detect, store
from office_br.scheduler import Scheduler

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
           "AVAXUSDT", "LINKUSDT", "NEARUSDT", "TIAUSDT", "SEIUSDT", "ONDOUSDT")
DDL = """CREATE TABLE IF NOT EXISTS br_live_cursor (
    sig_id TEXT PRIMARY KEY, last_bar_ts DOUBLE PRECISION NOT NULL
)"""


def enabled() -> bool:
    return os.getenv("BR_LIVE_TG", "0").lower() in ("1", "true", "yes", "on")


def symbols() -> tuple[str, ...]:
    raw = os.getenv("BR_LIVE_SYMBOLS", "").strip()
    return tuple(x.strip().upper() for x in raw.split(",") if x.strip()) if raw else SYMBOLS


def _epoch(row: dict) -> float:
    return datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")).timestamp()


def _bars(rows: Any) -> tuple[list, list, list, list, list]:
    return ([ _epoch(x) for x in rows],
            [float(x["open"]) for x in rows],
            [float(x["high"]) for x in rows],
            [float(x["low"]) for x in rows],
            [float(x["close"]) for x in rows])


def scan_symbol(db: str, symbol: str, fetch: Callable, now: float | None = None, *, htf_fetch: Callable | None = None) -> int:
    """Only newly closed confirmation bar; never replay old discoveries into Telegram."""
    now = time.time() if now is None else now
    bars = fetch(symbol, "15m", 240, closed_only=True)
    if not isinstance(bars, list) or len(bars) < 100:
        return 0
    t, o, h, l, c = _bars(bars)
    if now - (t[-1] + 900) >= 900 or t[-1] + 900 > now:
        return 0
    hits = detect.scan(t, o, h, l, c)
    new = 0
    for s in hits:
        if s["confirm_i"] != len(t) - 1:
            continue
        sid = store.record_signal(db, symbol, s, detect.HYP, now=now)
        if sid:
            new += 1
            print(f"[br-live] NEW {symbol} {s['direction']} id={sid}", flush=True)
            # Read-only SHADOW: independent from delivery and Office2. The
            # confirmation timestamp is the close of the newest M15 bar.
            try:
                from office_br.htf_map import build, scenario
                asof = t[-1] + 900
                market = build(symbol, asof, htf_fetch or fetch)
                hypothesis = scenario(market, float(s["entry"]), s["direction"])
                from office_br.ltf_confirmation import evaluate
                lower = evaluate(symbol, s, asof, htf_fetch or fetch)
                print("[br-htf-shadow] " + json.dumps({
                    "id": sid, "symbol": symbol, "asof": asof,
                    "direction": market["trend"]["direction"],
                    "health": market["health"], "scenario": hypothesis, "ltf": lower
                }, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(f"[br-htf-shadow] UNKNOWN {symbol} {type(exc).__name__}", flush=True)
    return new


def _pending(db: str) -> list[dict]:
    return store.rows(db, "WHERE status = 'NEW' AND msg_id IS NULL")


async def deliver(db: str, send: Callable, send_image: Callable | None = None, fetch: Callable | None = None) -> int:
    """Send first; acknowledge DB only with real Telegram message id. Retry on failure."""
    from office_bridge import _execute
    n = 0
    for row in _pending(db):
        # No stale startup notifications: only signals confirmed in last 4 minutes.
        if time.time() - (float(row["confirm_ts"]) + 900) > 240:
            _execute(db, "UPDATE br_test_signal SET status = 'EXPIRED_UNSENT' WHERE sig_id = ? AND msg_id IS NULL", (row["sig_id"],))
            continue
        try:
            if send_image is not None and fetch is not None:
                import os
                from office_br.live_image import render
                candles = await asyncio.to_thread(fetch, row["symbol"], "15m", 240, closed_only=True)
                png = await asyncio.to_thread(render, row, candles)
                try:
                    msg_id = await send_image(
                        png, '⚠️ B&R — ручне рішення. Replay V1/V2 збитковий.', row
                    )
                finally:
                    try: os.unlink(png)
                    except OSError: pass
            else:
                msg_id = await send(card.build_card(row), symbol=row["symbol"], direction=row["direction"])
            if not msg_id:
                print(f"[br-live] delivery pending {row['sig_id']}", flush=True)
                continue
            _execute(db, "UPDATE br_test_signal SET status = 'SENT', msg_id = ?, sent_ts = ?, last_error = NULL WHERE sig_id = ? AND msg_id IS NULL",
                     (int(msg_id), time.time(), row["sig_id"]))
            n += 1
            print(f"[br-live] SENT {row['sig_id']} tg_id={msg_id}", flush=True)
        except Exception as exc:
            _execute(db, "UPDATE br_test_signal SET last_error = ? WHERE sig_id = ?", (type(exc).__name__, row["sig_id"]))
            print(f"[br-live] send error {type(exc).__name__}: {exc}", flush=True)
    return n


def _cursor(db: str, sid: str, fallback: float) -> float:
    from office_bridge import _fetchone
    row = _fetchone(db, "SELECT last_bar_ts FROM br_live_cursor WHERE sig_id = ?", (sid,))
    return float(row[0]) if row else fallback


def _save_cursor(db: str, sid: str, ts: float) -> None:
    from office_bridge import _execute
    _execute(db, "INSERT INTO br_live_cursor(sig_id, last_bar_ts) VALUES (?,?) ON CONFLICT (sig_id) DO UPDATE SET last_bar_ts = EXCLUDED.last_bar_ts", (sid, ts))


async def track(db: str, fetch: Callable, send: Callable) -> int:
    """Conservative M1 paper tracking. Ambiguous same-bar TP/SL is NOT counted as a win."""
    from office_bridge import _execute
    n = 0
    active = store.rows(db, "WHERE status = 'SENT'")
    for row in active:
        sid = row["sig_id"]
        if time.time() - (float(row["confirm_ts"]) + 900) > 48 * 3600:
            msg_id = await send(f"B&R LIVE · B&R-{row['seq']} · {row['symbol']}: 48 год минуло, підсумок не визначено.",
                                reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"])
            if msg_id:
                _execute(db, "UPDATE br_test_signal SET status = 'TIMEOUT' WHERE sig_id = ?", (sid,))
            continue
        last = _cursor(db, sid, float(row["confirm_ts"]) + 840)
        candles = await asyncio.to_thread(fetch, row["symbol"], "1m", 120, closed_only=True)
        if not isinstance(candles, list) or not candles:
            continue
        # Never silently skip an interval if worker restarted or Futures was unavailable.
        first_ts = _epoch(candles[0])
        if first_ts > last + 60:
            print(f"[br-live] DATA_GAP {sid} last={last} first={first_ts}; no outcome assumed", flush=True)
            msg_id = await send(f"B&R LIVE · B&R-{row['seq']} · {row['symbol']}: прогалина у хвилинних даних; результат НЕВІДОМИЙ.",
                                reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"])
            if msg_id:
                _execute(db, "UPDATE br_test_signal SET status = 'DATA_GAP' WHERE sig_id = ?", (sid,))
            continue
        tg = json.loads(row["targets_json"])
        sg = 1 if row["direction"] == "LONG" else -1
        prev = {x["level"] for x in store.events(db, sid)}
        entry_seen = "ENTRY" in prev
        for b in candles:
            ts = _epoch(b)
            if ts <= last:
                continue
            high, low = float(b["high"]), float(b["low"])
            entry = float(row["entry"])
            if not entry_seen:
                if not (low <= entry <= high):
                    _save_cursor(db, sid, ts)
                    last = ts
                    continue
                entry_msg = await send(card.reminder_text(row, "ENTRY"),
                                       reply_to=int(row["msg_id"]), symbol=row["symbol"],
                                       direction=row["direction"])
                if not entry_msg:
                    break
                store.record_event(db, sid, "ENTRY", ts, entry, int(entry_msg))
                prev.add("ENTRY")
                entry_seen = True
                # A first-touch candle containing TP/SL has unknown ordering.
                stop_same = low <= float(row["sl"]) if sg > 0 else high >= float(row["sl"])
                tp_same = any((high >= float(t["p"]) if sg > 0 else low <= float(t["p"])) for t in tg[:3])
                if stop_same or tp_same:
                    warning = await send(
                        f"B&R LIVE · B&R-{row['seq']} · {row['symbol']}: вхід і TP/SL у тій самій M1-свічці. Порядок невідомий; результат не зараховано.",
                        reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"])
                    if warning:
                        store.record_event(db, sid, "AMBIGUOUS", ts, None, int(warning))
                        _execute(db, "UPDATE br_test_signal SET status = 'AMBIGUOUS' WHERE sig_id = ?", (sid,))
                        _save_cursor(db, sid, ts)
                    break
                _save_cursor(db, sid, ts)
                last = ts
                continue
            stop = low <= float(row["sl"]) if sg > 0 else high >= float(row["sl"])
            reached = [i + 1 for i, t in enumerate(tg[:3])
                       if (high >= float(t["p"]) if sg > 0 else low <= float(t["p"]))]
            new_tp = [i for i in reached if f"TP{i}" not in prev]
            if stop and new_tp:
                level = "AMBIGUOUS"
            elif stop:
                level = "SL"
            elif new_tp:
                level = f"TP{max(new_tp)}"
            else:
                _save_cursor(db, sid, ts)
                last = ts
                continue
            price = float(row["sl"]) if level == "SL" else (float(tg[max(new_tp)-1]["p"]) if new_tp and level != "AMBIGUOUS" else None)
            if level.startswith("TP") and len(new_tp) > 1:
                message_detail = "\n".join(card.reminder_text(row, f"TP{i}") for i in new_tp)
            else:
                message_detail = card.reminder_text(row, level)
            msg = (f"B&R LIVE · B&R-{row['seq']} · {row['symbol']}: "
                   + ("TP і SL торкнулися однієї M1-свічки — порядок НЕВІДОМИЙ" if level == "AMBIGUOUS"
                      else message_detail))
            try:
                msg_id = await send(msg, reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"])
                if not msg_id:
                    break  # don't advance cursor; retry
                if level.startswith("TP"):
                    # Higher target crossed implies all lower targets crossed.
                    for i in new_tp:
                        store.record_event(db, sid, f"TP{i}", ts, float(tg[i - 1]["p"]), int(msg_id))
                        prev.add(f"TP{i}")
                else:
                    store.record_event(db, sid, level, ts, price, int(msg_id))
                    prev.add(level)
                n += 1
                print(f"[br-live] EVENT {sid} {level} tg_id={msg_id}", flush=True)
                if level in ("SL", "AMBIGUOUS", "TP3"):
                    _execute(db, "UPDATE br_test_signal SET status = ? WHERE sig_id = ?", (level, sid))
                    _save_cursor(db, sid, ts)
                    break
                _save_cursor(db, sid, ts)
                last = ts
            except Exception as exc:
                print(f"[br-live] event retry {sid}: {type(exc).__name__}: {exc}", flush=True)
                break
    return n


async def monitor(db: str, send: Callable, fetch: Callable, send_image: Callable | None = None) -> None:
    """One low-frequency, isolated loop; failures never interrupt Office2."""
    from office_bridge import _execute
    _execute(db, DDL)
    store.init(db)
    seen: dict[str, float] = {}
    scheduler = Scheduler()
    data_alert_sent = False
    consecutive_partial = 0
    print(f"[br-live] monitor initialized enabled={enabled()} symbols={len(symbols())}", flush=True)
    await asyncio.sleep(45)
    while True:
        try:
            if enabled():
                scan_ok = scan_missing = scan_stale = scan_errors = new_signals = 0
                from office_market_data import hard_backoff_left
                hard_ban = hard_backoff_left()
                # During an exchange IP ban, don't fan out historical REST
                # requests every minute. Delivery/tracking still run safely
                # (tracking keeps its own fail-closed data-gap protection).
                scan_batch = symbols() if hard_ban <= 0 else ()
                dynamic = os.getenv("BR_LIVE_DYNAMIC_UNIVERSE", "0").strip() == "1"
                if dynamic:
                    from office_market_data import _http_get_json, source_health
                    weight = source_health().get("used_weight_1m")
                    if hard_ban > 0 or (isinstance(weight, (int, float)) and weight >= 1000):
                        scan_batch = ()
                    else:
                        scan_batch = await asyncio.to_thread(
                            scheduler.batch,
                            lambda: _http_get_json("https://fapi.binance.com/fapi/v1/exchangeInfo", {}),
                            hard_backoff=hard_ban,
                        )
                    print(f"[br-live] futures_universe={len(scheduler.universe)} batch={len(scan_batch)} weight={weight}",flush=True)
                if hard_ban > 0:
                    print(f"[br-live] BINANCE_BACKOFF remaining={hard_ban:.0f}s; new B&R scans paused", flush=True)
                # Drain fresh B&R signals as soon as each symbol is scanned.
                # A batch-wide queue can let later candidates expire while earlier
                # photo cards are rendered/sent serially (4-minute freshness gate).
                delivered = 0
                for sym in scan_batch:
                    try:
                        bars = await asyncio.to_thread(fetch, sym, "15m", 240, closed_only=True)
                        if not isinstance(bars, list) or len(bars) < 100:
                            scan_missing += 1
                            continue
                        ts = _epoch(bars[-1])
                        now_ts = time.time()
                        if ts + 900 > now_ts or now_ts - (ts + 900) >= 900:
                            scan_stale += 1
                            continue
                        if seen.get(sym) == ts:
                            scan_ok += 1
                            continue
                        # Do not mark a bar as processed before the detector succeeds.
                        found = await asyncio.to_thread(
                            scan_symbol, db, sym,
                            lambda _symbol, _tf, _limit, *, closed_only: bars,
                            now_ts,
                            htf_fetch=fetch,
                        )
                        seen[sym] = ts
                        scan_ok += 1
                        new_signals += found
                        if found:
                            delivered += await deliver(db, send, send_image=send_image, fetch=fetch)
                    except Exception as exc:
                        scan_errors += 1
                        print(f"[br-live] scan {sym}: {type(exc).__name__}: {exc}", flush=True)
                # One operational alert per sustained coverage degradation,
                # not a new trading signal, and one recovery notice.
                if hard_ban > 0 or (scan_ok < len(symbols())):
                    consecutive_partial += 1
                else:
                    consecutive_partial = 0
                if consecutive_partial >= 3 and not data_alert_sent:
                    try:
                        alert_id = await send(
                            f"⚠️ B&R LIVE · СКАНУВАННЯ ОБМЕЖЕНО: "
                            f"{scan_ok}/{len(symbols())} пар; "
                            f"Binance backoff {hard_ban:.0f} с. "
                            "Непідтверджені входи не надсилаються."
                        )
                        if alert_id:
                            data_alert_sent = True
                    except Exception as exc:
                        print(f"[br-live] feed alert error: {type(exc).__name__}", flush=True)
                if data_alert_sent and consecutive_partial == 0:
                    try:
                        recovered_id = await send(
                            f"✅ B&R LIVE · М15 ВІДНОВЛЕНО: "
                            f"{scan_ok}/{len(symbols())}. Це не сигнал для входу."
                        )
                        if recovered_id:
                            data_alert_sent = False
                    except Exception as exc:
                        print(f"[br-live] recovery alert error: {type(exc).__name__}", flush=True)
                # Final drain also retries previously pending deliveries.
                delivered += await deliver(db, send, send_image=send_image, fetch=fetch)
                tracked = await track(db, fetch, send)
                if scan_stale or scan_missing or scan_errors:
                    print(f"[br-live] DEGRADED_FEED stale={scan_stale} missing={scan_missing} errors={scan_errors}; stale bars blocked", flush=True)
                # Operational heartbeat: an empty scan is not a delivery failure.
                print(f"[br-live] scan health ok={scan_ok}/{len(scan_batch)} missing={scan_missing} stale={scan_stale} errors={scan_errors} new={new_signals} sent={delivered} events={tracked}", flush=True)
        except Exception as exc:
            print(f"[br-live] loop: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(60)
