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
    # A signal must still fit the same four-minute freshness window used by
    # deliver(); otherwise it is inserted only to be immediately EXPIRED_UNSENT.
    if now - (t[-1] + 900) > 240 or t[-1] + 900 > now:
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


def trend_text(fetch: Callable, symbol: str, direction: str) -> str | None:
    """Рядок «Тренд: 4 год … · 1 год …» для картки B&R: сторона середньої за 200 закритих свічок на H4 і H1. Збій даних → None (картка йде без рядка)."""
    try:
        from office_td.swing import h4_from_h1
        rows = fetch(symbol, "1h", 900, closed_only=True)
        if not isinstance(rows, list) or len(rows) < 200: return None
        c1 = [float(x["close"]) for x in rows]; up1 = c1[-1] > sum(c1[-200:]) / 200
        b = h4_from_h1(rows); up4 = None
        if b is not None and len(b["c"]) >= 200: up4 = bool(b["c"][-1] > float(b["c"][-200:].mean()))
        return card.trend_line(direction, up4, up1)
    except Exception as exc:  # noqa: BLE001 — підказка не має блокувати доставку
        print(f"[br-live] trend line skipped {symbol}: {type(exc).__name__}", flush=True)
        return None


def _pending(db: str) -> list[dict]:
    return store.rows(db, "WHERE status = 'NEW' AND msg_id IS NULL")


async def deliver(db: str, send: Callable, send_image: Callable | None = None, fetch: Callable | None = None) -> int:
    """Send first; acknowledge DB only with real Telegram message id. Retry on failure."""
    from office_bridge import _execute
    n = 0
    for row in _pending(db):
        # No stale startup notifications: only signals confirmed in last 4 minutes.
        if time.time() - (float(row["confirm_ts"]) + (14400 if card.is_swing(row) else 900)) > (900 if card.is_swing(row) else 240):
            _execute(db, "UPDATE br_test_signal SET status = 'EXPIRED_UNSENT' WHERE sig_id = ? AND msg_id IS NULL", (row["sig_id"],))
            continue
        try:
            v2_line = None
            if not card.is_td(row):      # v2-мітка — лише для B&R; TD-V1 має власну картку
                try:
                    from office_br import v2
                    bucket = int(float(row["created_ts"]) // 900) * 900
                    v2_line = v2.line(row, store.rows(db, "WHERE created_ts >= ? AND created_ts < ?", (bucket, bucket + 900)))
                except Exception as exc_v2:  # мітка інформаційна: збій не має блокувати доставку
                    print(f"[br-live] v2 label skipped: {type(exc_v2).__name__}", flush=True)
            trend = None
            if fetch is not None and not card.is_td(row):   # підказка про тренд — лише для B&R
                trend = await asyncio.to_thread(trend_text, fetch, row["symbol"], row["direction"])
            if send_image is not None and fetch is not None:
                import os
                from office_br.live_image import render
                sw = card.is_swing(row)       # СВІНГ малюється на 4-годинних свічках, ІНТРАДЕЙ — на M15
                candles = await asyncio.to_thread(fetch, row["symbol"], "4h" if sw else "15m", 130 if sw else 240, closed_only=True)
                png = await asyncio.to_thread(render, row, candles)
                try:
                    msg_id = await send_image(
                        png, card.build_caption(row, v2_line, trend)[0], row
                    )
                finally:
                    try: os.unlink(png)
                    except OSError: pass
            else:
                msg_id = await send(card.build_card(row, v2_line, trend), symbol=row["symbol"], direction=row["direction"])
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


def reconcile_pre_ready_ambiguous_audit(db: str) -> int:
    """Backfill missing B&R audit rows for legacy PRE_READY_ENTRY terminal states.

    This records only the ambiguous state in the B&R event ledger. It never sends
    Telegram messages or fabricates Telegram message IDs.
    """
    repaired = 0
    for row in store.rows(db, "WHERE status = 'AMBIGUOUS' AND sent_ts IS NOT NULL"):
        sid = row["sig_id"]
        events = store.events(db, sid)
        if any(event["level"] == "AMBIGUOUS" for event in events):
            continue
        entry = next((event for event in events if event["level"] == "ENTRY"), None)
        ready_sent_ts = row.get("sent_ts")
        if entry is None or ready_sent_ts is None:
            continue
        if float(entry["touched_ts"]) >= float(ready_sent_ts):
            continue
        if store.record_event(db, sid, "AMBIGUOUS", float(entry["touched_ts"]), None):
            repaired += 1
    return repaired


_GAP_TRIES: dict = {}


async def track(db: str, fetch: Callable, send: Callable) -> int:
    """Conservative M1 paper tracking. Ambiguous same-bar TP/SL is NOT counted as a win."""
    from office_bridge import _execute
    n = 0
    active = store.rows(db, "WHERE status = 'SENT'")
    for row in active:
        sid = row["sig_id"]
        if time.time() - (float(row["confirm_ts"]) + (14400 if card.is_swing(row) else 900)) > card.hold_hours(row) * 3600:
            px_t = None; tail = ""
            if card.is_td(row):      # ІНТРАДЕЙ/СВІНГ: час вийшов — показуємо результат за ринком на цей момент і просимо закрити (у СВІНГу ≈45% угод закриваються саме так і здебільшого в плюсі)
                try:
                    cs = await asyncio.to_thread(fetch, row["symbol"], "1m", 5, closed_only=True)
                    px_t = float(cs[-1]["close"]) if isinstance(cs, list) and cs else None
                    if px_t is not None:
                        sg_t = 1 if row["direction"] == "LONG" else -1; rk = abs(float(row["entry"]) - float(row["sl"]))
                        r_t = sg_t * (px_t - float(row["entry"])) / rk if rk > 0 else 0.0
                        num = f"{r_t:+.1f}".replace(".", ",").replace("-", "−"); tail = f" Зараз {num}R ({'+' if r_t >= 0 else '−'}${abs(10 * r_t):.0f}) — закрий угоду за ринком."
                except Exception:  # noqa: BLE001
                    px_t = None
            msg_id = await send(f"{card.head(row)} · {row['symbol']}: {card.hold_text(row).replace('до ', '')} минуло, підсумок не визначено.{tail}",
                                reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"])
            if msg_id:
                _execute(db, "UPDATE br_test_signal SET status = 'TIMEOUT' WHERE sig_id = ?", (sid,))
                if px_t is not None:
                    try: store.record_event(db, sid, "TIMEOUT", time.time(), px_t)
                    except Exception: pass
            continue
        # Paper ENTRY tracking starts only after the READY card was actually sent.
        # Clamp any persisted cursor too, so a restart cannot replay pre-delivery candles.
        ready_sent_ts = row.get("sent_ts")
        if ready_sent_ts is None:
            print(f"[br-live] missing READY sent_ts {sid}; tracking deferred", flush=True)
            continue
        # Check persisted ENTRY before reading cursors/candles: legacy entries
        # touched before READY delivery cannot produce later paper outcomes.
        existing_events = store.events(db, sid)
        existing_entry = next((x for x in existing_events if x["level"] == "ENTRY"), None)
        if existing_entry and float(existing_entry["touched_ts"]) < float(ready_sent_ts):
            # Preserve the audit trail without claiming a Telegram delivery.
            try:
                store.record_event(db, sid, "AMBIGUOUS", float(existing_entry["touched_ts"]), None)
            except Exception as exc:
                print(f"[br-live] ambiguous audit event {sid}: {type(exc).__name__}", flush=True)
            _execute(db, "UPDATE br_test_signal SET status = 'AMBIGUOUS' WHERE sig_id = ? AND status = 'SENT'", (sid,))
            print(f"[br-live] PRE_READY_ENTRY {sid}; outcome suppressed", flush=True)
            continue
        last = max(_cursor(db, sid, float(ready_sent_ts)), float(ready_sent_ts))
        need_1m = max(120, min(1000, int((time.time() - last) / 60) + 10))     # після простою воркера (OOM/деплой) докачуємо хвилинні свічки від курсора, а не лише останні 2 год
        candles = await asyncio.to_thread(fetch, row["symbol"], "1m", need_1m, closed_only=True)
        if not isinstance(candles, list) or not candles:
            continue
        # Never silently skip an interval if worker restarted or Futures was unavailable.
        first_ts = _epoch(candles[0])
        if first_ts > last + 60 and card.is_td(row):
            _GAP_TRIES[sid] = _GAP_TRIES.get(sid, 0) + 1            # ІНТРАДЕЙ/СВІНГ: тимчасова нестача хвилинних свічок (ліміт API, кеш) — повторюємо наступним циклом; DATA_GAP лише після 8 невдалих циклів поспіль
            if _GAP_TRIES[sid] < 8:
                if _GAP_TRIES[sid] == 1: print(f"[br-live] gap {sid}: докачка не покрила курсор, повтор", flush=True)
                continue
        elif sid in _GAP_TRIES:
            _GAP_TRIES.pop(sid, None)
        if first_ts > last + 60:
            _GAP_TRIES.pop(sid, None)
            print(f"[br-live] DATA_GAP {sid} last={last} first={first_ts}; no outcome assumed", flush=True)
            msg_id = await send(f"{card.head(row)} · {row['symbol']}: прогалина у хвилинних даних; результат НЕВІДОМИЙ.",
                                reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"])
            if msg_id:
                _execute(db, "UPDATE br_test_signal SET status = 'DATA_GAP' WHERE sig_id = ?", (sid,))
            continue
        tg = json.loads(row["targets_json"])
        sg = 1 if row["direction"] == "LONG" else -1
        prev = {x["level"] for x in existing_events}
        entry_seen = "ENTRY" in prev
        if card.is_td(row) and not entry_seen:
            # TD-V1: вхід M15 = закриття свічки підтвердження, а картка йде одразу після нього. Тож вхід рахується в момент картки
            # (так само, як у бектесті, де вхід = закриття свічки), без очікування повернення ціни до рівня входу.
            store.record_event(db, sid, "ENTRY", float(ready_sent_ts), float(row["entry"]), None)
            prev.add("ENTRY")
            entry_seen = True
            _save_cursor(db, sid, float(ready_sent_ts))
            last = max(last, float(ready_sent_ts))
        for b in candles:
            ts = _epoch(b)
            if ts <= last:
                continue
            high, low = float(b["high"]), float(b["low"])
            entry = float(row["entry"])
            if not entry_seen:
                if not (low <= entry <= high):
                    # Вхід не торкнуто (рішення власниці 23.11.2026): ціна зачепила стоп → одне попередження, сигнал лишається чинним; ціна пішла до першої цілі → «скасовано» і кінець супроводу.
                    if "PRESTOP" not in prev and ((low <= float(row["sl"])) if sg > 0 else (high >= float(row["sl"]))):
                        w_msg = await send(card.prestop_text(row), reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"])
                        if not w_msg:
                            break
                        store.record_event(db, sid, "PRESTOP", ts, None, int(w_msg)); prev.add("PRESTOP"); n += 1
                        print(f"[br-live] PRESTOP {sid} tg_id={w_msg}", flush=True)
                    elif tg and ((high >= float(tg[0]["p"])) if sg > 0 else (low <= float(tg[0]["p"]))):
                        c_msg = await send(card.cancel_text(row), reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"])
                        if not c_msg:
                            break
                        store.record_event(db, sid, "CANCEL", ts, None, int(c_msg))
                        _execute(db, "UPDATE br_test_signal SET status = 'CANCEL' WHERE sig_id = ?", (sid,))
                        _save_cursor(db, sid, ts); n += 1
                        print(f"[br-live] CANCEL {sid} (ціль без входу) tg_id={c_msg}", flush=True)
                        break
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
                        f"{card.head(row)} · {row['symbol']}: вхід і TP/SL у тій самій M1-свічці. Порядок невідомий; результат не зараховано.",
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
            msg = (f"{card.head(row)} · {row['symbol']}: "
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
                if level in ("SL", "AMBIGUOUS", f"TP{min(3, len(tg))}"):
                    _execute(db, "UPDATE br_test_signal SET status = ? WHERE sig_id = ?", (level, sid))
                    _save_cursor(db, sid, ts)
                    break
                _save_cursor(db, sid, ts)
                last = ts
            except Exception as exc:
                print(f"[br-live] event retry {sid}: {type(exc).__name__}: {exc}", flush=True)
                break
    return n


def repair_outage_data_gap(db: str, now: float | None = None) -> int:
    """Одноразово (22.11.2026): після простою воркера (OOM, ~12 год) усі відкриті ІНТРАДЕЙ/СВІНГ були помилково позначені DATA_GAP (докачка свічок була лише 2 год). Повертаємо їх у SENT, щоб супровід (стоп/ціль/час, табло, нагадування) продовжився з докачкою від курсора."""
    from office_bridge import _execute, _fetchone, _fetchall
    now = time.time() if now is None else now
    _execute(db, "CREATE TABLE IF NOT EXISTS br_repair (key TEXT PRIMARY KEY, ts DOUBLE PRECISION NOT NULL, n INTEGER)")
    if _fetchone(db, "SELECT 1 FROM br_repair WHERE key = 'dg_outage_20261122b'"):
        return 0
    rows = _fetchall(db, "SELECT sig_id FROM br_test_signal WHERE status = 'DATA_GAP' AND msg_id IS NOT NULL AND sent_ts >= ? AND (sig_id LIKE 'TD|%' OR sig_id LIKE 'SW|%')", (now - 11 * 86400,))
    for (sid,) in rows:
        _execute(db, "UPDATE br_test_signal SET status = 'SENT' WHERE sig_id = ? AND status = 'DATA_GAP'", (sid,))
    _execute(db, "INSERT INTO br_repair(key, ts, n) VALUES ('dg_outage_20261122b', ?, ?) ON CONFLICT DO NOTHING", (now, len(rows)))
    return len(rows)


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
    if enabled():
        try:
            n_dg = await asyncio.to_thread(repair_outage_data_gap, db)
            if n_dg:
                print(f"[br-live] повернуто з DATA_GAP у SENT після простою: {n_dg}", flush=True)
        except Exception as exc:
            print(f"[br-live] repair DATA_GAP: {type(exc).__name__}: {exc}", flush=True)
        try:
            repaired = await asyncio.to_thread(reconcile_pre_ready_ambiguous_audit, db)
            if repaired:
                print(f"[br-live] reconciled PRE_READY_ENTRY audit events={repaired}", flush=True)
        except Exception as exc:
            print(f"[br-live] ambiguous audit reconciliation: {type(exc).__name__}", flush=True)
    await asyncio.sleep(45)
    while True:
        try:
            if enabled():
                scan_ok = scan_missing = scan_stale = scan_errors = new_signals = 0
                # TD-V1 (ТЕСТ) рахується в сервісі Mini App (office_td.service) і пише сигнали в БД; тут лише доставка/супровід (без важких обчислень у Worker).
                # Prioritize existing paper-position lifecycle updates before fresh scans.
                # A slow scan/card send must not hold TP/SL notifications until cycle end.
                # On restart, drain persisted READY candidates before lifecycle
                # tracking and scans. The four-minute guard still blocks stale cards.
                delivered = 0
                try:
                    delivered += await deliver(db, send, send_image=send_image, fetch=fetch)
                except Exception as exc:
                    print(f"[br-live] pending delivery: {type(exc).__name__}: {exc}", flush=True)
                tracked = 0
                try:
                    tracked = await track(db, fetch, send)
                except Exception as exc:
                    print(f"[br-live] track: {type(exc).__name__}: {exc}", flush=True)
                try:                    # TD-V1: інформаційне нагадування про відкриту угоду в плюсі (відповідь на картку; без дій)
                    from office_td import remind
                    await remind.remind_open(db, fetch, send)
                except Exception as exc:
                    print(f"[td-remind] {type(exc).__name__}: {exc}", flush=True)
                if send_image is not None:           # Табло відкритих угод раз на добу о 09:00 за Києвом (BOARD=0 вимикає)
                    try:
                        from office_td import board
                        await board.daily(db, fetch, send_image)
                    except Exception as exc:
                        print(f"[board] {type(exc).__name__}: {exc}", flush=True)
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
                # Drain each fresh candidate immediately after its symbol scan.
                # Keep the running delivery count, including the restart drain above.
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
                if scan_stale or scan_missing or scan_errors:
                    print(f"[br-live] DEGRADED_FEED stale={scan_stale} missing={scan_missing} errors={scan_errors}; stale bars blocked", flush=True)
                # Operational heartbeat: an empty scan is not a delivery failure.
                print(f"[br-live] scan health ok={scan_ok}/{len(scan_batch)} missing={scan_missing} stale={scan_stale} errors={scan_errors} new={new_signals} sent={delivered} events={tracked}", flush=True)
        except Exception as exc:
            print(f"[br-live] loop: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(60)
