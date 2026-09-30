"""Карта ліквідацій із БЕЗКОШТОВНИХ джерел (без платних постачальників).

Два різні шари, які НЕ змішуються й підписані окремо:
  1. ФАКТИЧНІ ліквідації Binance: потік `!forceOrder@arr` (усі USDT-перпи) за останні 24 год, згруповані за ціною. Це те, що вже сталося, а не прогноз.
  2. ОЦІНКА з відкритого інтересу і плеча (модель): приріст OI за годину = нові позиції на ціні тієї години; поділ на лонг/шорт за співвідношенням
     акаунтів; плечі 5/10/25/50/100× із припущеними вагами; ціна ліквідації = ціна входу ∓ 1/плече ± запас мейнтенанс-маржі. Позиція вважається вже
     ліквідованою, якщо пізніша свічка зайшла за її рівень. Це модель, а не дані біржі: точні позиції й плечі Binance не публікує.
Жодного впливу на вхід/ордери: лише контекст графіка й Mini App. Немає даних → чесно «недоступно».
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

WINDOW_SEC = 24 * 3600.0
MAX_EVENTS_PER_SYMBOL = 4000
_CHECK_SEC = 30.0
SILENCE_ROTATE_SEC = 600.0           # на потоці всього ринку ліквідації йдуть постійно: 10 хв тиші = маршрут мертвий → наступна адреса
STREAM_BASES = ("wss://fstream.binance.com/market/stream", "wss://fstream.binance.com/stream")
TIERS: Tuple[Tuple[int, float], ...] = ((5, 0.15), (10, 0.30), (25, 0.30), (50, 0.15), (100, 0.10))   # (плече, припущена вага обсягу)
MMR = 0.005                          # припущений запас мейнтенанс-маржі (0,5%)
EST_RANGE_PCT = 15.0                 # показуємо рівні не далі ±15% від ціни
OI_MAX_AGE_SEC = 2 * 3600.0          # OI-історія старша за 2 год — оцінку не будуємо

_LOCK = threading.RLock()
_EVENTS: Dict[str, Deque[Tuple[float, float, float, str]]] = {}    # символ → (ts, ціна, обсяг USDT, сторона ордера)
_STATE: Dict[str, Any] = {"connected": False, "events": 0, "last_event": 0.0, "connects": 0, "rotations": 0, "base_idx": 0, "last_error": None, "started_at": 0.0}
_THREAD: Optional[threading.Thread] = None


def enabled() -> bool:
    return os.getenv("OFFICE_LIQ_MAP", "1").strip() != "0"


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def parse_event(raw: Any) -> Optional[Dict[str, Any]]:
    """Розбір повідомлення `forceOrder` (окреме або в обгортці combined stream). None — не ліквідація."""
    msg = raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            msg = json.loads(raw)
        except ValueError:
            return None
    if isinstance(msg, dict) and isinstance(msg.get("data"), dict):
        msg = msg["data"]
    if not isinstance(msg, dict) or str(msg.get("e") or "") != "forceOrder":
        return None
    o = msg.get("o")
    if not isinstance(o, dict):
        return None
    sym = str(o.get("s") or "").upper().strip()
    side = str(o.get("S") or "").upper().strip()
    price = _f(o.get("ap")) or _f(o.get("p"))
    qty = _f(o.get("z")) or _f(o.get("q")) or _f(o.get("l"))
    ts_ms = _f(o.get("T")) or _f(msg.get("E"))
    if not sym or side not in ("BUY", "SELL") or not price or not qty or price <= 0 or qty <= 0:
        return None
    return {"symbol": sym, "side": side, "price": price, "notional": price * qty, "ts": (ts_ms / 1000.0) if ts_ms else time.time(),
            "kind": "short_liq" if side == "BUY" else "long_liq"}   # BUY-ордер закриває шорт (ліквідація шорта); SELL — ліквідація лонга


def ingest(ev: Dict[str, Any]) -> None:
    with _LOCK:
        dq = _EVENTS.setdefault(ev["symbol"], deque(maxlen=MAX_EVENTS_PER_SYMBOL))
        dq.append((float(ev["ts"]), float(ev["price"]), float(ev["notional"]), str(ev["side"])))
        _STATE["events"] += 1
        _STATE["last_event"] = time.time()


def _nice_step(price: float) -> float:
    """Крок групування ≈ 0,25% ціни, округлений до 1-2-5."""
    import math

    raw = max(price * 0.0025, 1e-12)
    p = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * p:
            return m * p
    return 10 * p


def real_snapshot(symbol: str, now: Optional[float] = None, top: int = 8) -> Dict[str, Any]:
    """Фактичні ліквідації символу за 24 год: підсумки й найбільші цінові групи (лонг-ліквідації / шорт-ліквідації)."""
    now = time.time() if now is None else now
    sym = str(symbol or "").upper()
    with _LOCK:
        evs = [e for e in _EVENTS.get(sym, ()) if now - e[0] <= WINDOW_SEC]
        last_any = _STATE["last_event"]
        connected = _STATE["connected"]
    base = {"label": "фактичні ліквідації Binance за 24 год (не прогноз)", "symbol": sym, "window_h": 24, "stream_connected": connected,
            "stream_last_event_age_sec": round(now - last_any, 1) if last_any else None}
    if not evs:
        return {**base, "count": 0, "long_liq_usd": 0.0, "short_liq_usd": 0.0, "buckets": []}
    step = _nice_step(sum(e[1] for e in evs) / len(evs))
    buckets: Dict[Tuple[str, float], float] = {}
    longs = shorts = 0.0
    for ts, px, nt, side in evs:
        kind = "short_liq" if side == "BUY" else "long_liq"
        if kind == "long_liq":
            longs += nt
        else:
            shorts += nt
        k = (kind, round(px // step * step, 12))
        buckets[k] = buckets.get(k, 0.0) + nt
    rows = sorted(({"kind": k[0], "price": k[1], "price_to": k[1] + step, "usd": round(v, 2)} for k, v in buckets.items()), key=lambda r: -r["usd"])[:top]
    return {**base, "count": len(evs), "long_liq_usd": round(longs, 2), "short_liq_usd": round(shorts, 2), "step": step, "buckets": rows}


def snapshot_all(top_symbols: int = 15, top_buckets: int = 8, now: Optional[float] = None) -> Dict[str, Any]:
    """Компактний зліпок для БД (web читає його: потік живе у worker). Лише символи з найбільшим обсягом ліквідацій + BTC/ETH."""
    now = time.time() if now is None else now
    with _LOCK:
        totals = {s: sum(e[2] for e in dq if now - e[0] <= WINDOW_SEC) for s, dq in _EVENTS.items()}
    names = sorted(totals, key=lambda s: -totals[s])[:top_symbols]
    for s in ("BTCUSDT", "ETHUSDT"):
        if s not in names and s in totals:
            names.append(s)
    return {"at": now, "stream": dict(stream_state()), "symbols": {s: real_snapshot(s, now, top_buckets) for s in names}}


_LAST_PERSIST = 0.0


def persist(db_path: str, every_sec: float = 1800.0, now: Optional[float] = None) -> bool:
    """Записати зліпок у БД (подія LIQ_MAP), не частіше ніж раз на every_sec: потік живе у worker, а Mini App — у web."""
    global _LAST_PERSIST
    now = time.time() if now is None else now
    if now - _LAST_PERSIST < every_sec:
        return False
    _LAST_PERSIST = now
    try:
        from office_bridge import log_event

        log_event(db_path, "LIQ_MAP", snapshot_all(now=now))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[liq-map] persist failed: {type(exc).__name__}: {exc}")
        return False


def latest_persisted(db_path: str, symbol: str, max_age_sec: float = 2400.0, now: Optional[float] = None) -> Dict[str, Any]:
    """Останній зліпок із БД для символу (для web). Старіший за max_age_sec — «недоступно»."""
    now = time.time() if now is None else now
    try:
        from office_bridge import _fetchall

        rows = _fetchall(db_path, "SELECT payload_json FROM office_events WHERE event_type = ? ORDER BY id DESC LIMIT 1", ("LIQ_MAP",))
        payload = json.loads(rows[0][0]) if rows and isinstance(rows[0][0], str) else (dict(rows[0][0]) if rows else None)
    except Exception:  # noqa: BLE001
        payload = None
    if not payload:
        return {"ok": False, "note": "потік ліквідацій ще не записав даних"}
    age = now - float(payload.get("at") or 0)
    if age > max_age_sec:
        return {"ok": False, "note": f"зліпок ліквідацій застарів ({age / 60:.0f} хв) — потік не пише", "age_sec": round(age, 1)}
    sym = str(symbol or "").upper()
    one = (payload.get("symbols") or {}).get(sym)
    if one is None:
        return {"ok": True, "age_sec": round(age, 1), "stream": payload.get("stream"),
                "real": {"label": "фактичні ліквідації Binance за 24 год (не прогноз)", "symbol": sym, "count": 0, "buckets": [], "long_liq_usd": 0.0, "short_liq_usd": 0.0,
                         "note": "за 24 год ліквідацій цього символу в зліпку немає (у зліпок потрапляють найбільші за обсягом)"}}
    return {"ok": True, "age_sec": round(age, 1), "stream": payload.get("stream"), "real": one}


def stream_state() -> Dict[str, Any]:
    with _LOCK:
        d = dict(_STATE)
    d["last_event_age_sec"] = round(time.time() - d["last_event"], 1) if d["last_event"] else None
    d["symbols"] = len(_EVENTS)
    d["base"] = STREAM_BASES[d["base_idx"] % len(STREAM_BASES)]
    return d


# ---------------- потік (worker) ----------------
async def _session() -> None:
    import aiohttp

    base = STREAM_BASES[_STATE["base_idx"] % len(STREAM_BASES)]
    url = f"{base}?streams=!forceOrder@arr"
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15)
    started = time.time()
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.ws_connect(url, heartbeat=20.0, max_msg_size=0) as ws:
            with _LOCK:
                _STATE.update(connected=True, last_error=None)
                _STATE["connects"] += 1
            print(f"[liq-map] підключено {base}", flush=True)
            async for m in ws:
                if m.type == aiohttp.WSMsgType.TEXT:
                    ev = parse_event(m.data)
                    if ev:
                        ingest(ev)
                elif m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                    break
                quiet = time.time() - max(_STATE["last_event"], started)
                if quiet > SILENCE_ROTATE_SEC:   # повідомлення (пінги) можуть іти, а ліквідацій нема — маршрут мертвий
                    with _LOCK:
                        _STATE["rotations"] += 1
                        _STATE["base_idx"] += 1
                        _STATE["last_error"] = f"тиша {quiet:.0f} с → інша адреса"
                    print(f"[liq-map] тиша {quiet:.0f} с без ліквідацій — інша адреса", flush=True)
                    await ws.close()
                    break


async def _watchdog_loop() -> None:
    backoff = 1.0
    while True:
        t0 = time.time()
        try:
            await asyncio.wait_for(_session_with_silence(), timeout=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            with _LOCK:
                _STATE["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
        with _LOCK:
            _STATE["connected"] = False
        await asyncio.sleep(backoff)
        backoff = 1.0 if time.time() - t0 > 60 else min(backoff * 2, 120.0)


async def _session_with_silence() -> None:
    """Сесія + сторож: якщо на адресі взагалі нема повідомлень (навіть без ліквідацій) 10 хв — теж перемикаємось."""
    task = asyncio.ensure_future(_session())
    started = time.time()
    try:
        while not task.done():
            await asyncio.sleep(_CHECK_SEC)
            quiet = time.time() - max(_STATE["last_event"], started)
            if quiet > SILENCE_ROTATE_SEC and not task.done():
                with _LOCK:
                    _STATE["rotations"] += 1
                    _STATE["base_idx"] += 1
                    _STATE["last_error"] = f"тиша {quiet:.0f} с → інша адреса"
                print(f"[liq-map] тиша {quiet:.0f} с — інша адреса", flush=True)
                task.cancel()
                break
        await asyncio.gather(task, return_exceptions=True)
    finally:
        if not task.done():
            task.cancel()


def start() -> bool:
    """Запуск потоку в окремому потоці (idempotent). False, якщо вимкнено OFFICE_LIQ_MAP=0."""
    global _THREAD
    if not enabled():
        return False
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        _STATE["started_at"] = time.time()

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_watchdog_loop())
            except Exception:  # noqa: BLE001
                pass

        _THREAD = threading.Thread(target=_run, name="liq-map", daemon=True)
        _THREAD.start()
    return True


def reset_for_tests() -> None:
    with _LOCK:
        _EVENTS.clear()
        _STATE.update(connected=False, events=0, last_event=0.0, connects=0, rotations=0, base_idx=0, last_error=None, started_at=0.0)


# ---------------- оцінка з OI і плеча ----------------
def _hour(ts: Any) -> Optional[int]:
    try:
        if isinstance(ts, (int, float)):
            return int(ts // 3600)
        return int(datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() // 3600)
    except (TypeError, ValueError):
        return None


def estimate(candles_1h: List[Dict[str, Any]], oi_hist: List[Dict[str, Any]], ls_hist: List[Dict[str, Any]], now: Optional[float] = None,
             top: int = 6) -> Dict[str, Any]:
    """Орієнтовна карта ліквідацій (модель). candles_1h: ts/high/low/close; oi_hist: {oi (USDT), timestamp}; ls_hist: {ratio, timestamp}.
    Повертає кластери нижче ціни (ліквідації лонгів) і вище (ліквідації шортів) з орієнтовним обсягом у USDT."""
    now = time.time() if now is None else now
    base = {"label": "ОРІЄНТОВНА оцінка з відкритого інтересу і плеча (модель, не дані біржі)", "model": {"tiers": [list(t) for t in TIERS], "mmr_pct": MMR * 100}}
    bars = [c for c in candles_1h or [] if isinstance(c, dict) and _hour(c.get("ts")) is not None]
    oi = [o for o in oi_hist or [] if isinstance(o, dict) and _f(o.get("oi")) is not None and _hour(o.get("timestamp")) is not None]
    if len(bars) < 12 or len(oi) < 3:
        return {**base, "ok": False, "note": "замало свічок або історії відкритого інтересу — оцінку не будуємо"}
    last_oi_h = _hour(oi[-1]["timestamp"])
    if last_oi_h is None or now - last_oi_h * 3600.0 > OI_MAX_AGE_SEC + 3600.0:
        return {**base, "ok": False, "note": "історія відкритого інтересу застаріла — оцінку не будуємо"}
    by_hour = {_hour(c["ts"]): c for c in bars}
    ls_by = {_hour(x.get("timestamp")): _f(x.get("ratio")) for x in ls_hist or [] if isinstance(x, dict) and _f(x.get("ratio"))}
    price_now = float(bars[-1]["close"])
    clusters: Dict[Tuple[str, float], float] = {}
    step = _nice_step(price_now)
    hours_sorted = sorted(by_hour)
    last_ratio = 1.0
    prev = None
    for o in sorted(oi, key=lambda x: _hour(x["timestamp"])):
        h = _hour(o["timestamp"])
        val = float(o["oi"])
        if h in ls_by:
            last_ratio = ls_by[h]
        if prev is None:
            prev = val
            continue
        delta = val - prev
        prev = val
        c = by_hour.get(h)
        if delta <= 0 or c is None:
            continue
        p = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
        long_share = last_ratio / (1.0 + last_ratio)
        later = [by_hour[x] for x in hours_sorted if x > h]
        lo_after = min((float(x["low"]) for x in later), default=None)
        hi_after = max((float(x["high"]) for x in later), default=None)
        for lev, w in TIERS:
            liq_long = p * (1.0 - 1.0 / lev + MMR)
            liq_short = p * (1.0 + 1.0 / lev - MMR)
            if lo_after is None or lo_after > liq_long:                  # лонг ще не ліквідований: ціна не заходила під рівень
                if abs(liq_long / price_now - 1.0) * 100 <= EST_RANGE_PCT and liq_long < price_now:
                    k = ("long_liq", round(liq_long // step * step, 12))
                    clusters[k] = clusters.get(k, 0.0) + delta * long_share * w
            if hi_after is None or hi_after < liq_short:
                if abs(liq_short / price_now - 1.0) * 100 <= EST_RANGE_PCT and liq_short > price_now:
                    k = ("short_liq", round(liq_short // step * step, 12))
                    clusters[k] = clusters.get(k, 0.0) + delta * (1.0 - long_share) * w
    rows = [{"kind": k[0], "price": k[1], "price_to": k[1] + step, "usd": round(v, 2)} for k, v in clusters.items() if v > 0]
    below = sorted([r for r in rows if r["kind"] == "long_liq"], key=lambda r: -r["usd"])[:top]
    above = sorted([r for r in rows if r["kind"] == "short_liq"], key=lambda r: -r["usd"])[:top]
    return {**base, "ok": True, "price": price_now, "step": step, "below": below, "above": above,
            "oi_as_of": datetime.fromtimestamp(last_oi_h * 3600.0, tz=timezone.utc).isoformat()}


def fetch_estimate(symbol: str) -> Dict[str, Any]:
    """Оцінка для символу з живих даних Binance (кеш 10 хв): свічки 1г (WS/REST), історія OI і співвідношення акаунтів."""
    sym = str(symbol or "").upper()
    hit = _EST_CACHE.get(sym)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    try:
        from office_market_data import _http_get_json, fetch_candles

        bars = fetch_candles(sym, "1h", 168)
        oi_raw = _http_get_json("https://fapi.binance.com/futures/data/openInterestHist", {"symbol": sym, "period": "1h", "limit": 168})
        ls_raw = _http_get_json("https://fapi.binance.com/futures/data/globalLongShortAccountRatio", {"symbol": sym, "period": "1h", "limit": 168})
        oi = [{"oi": x.get("sumOpenInterestValue"), "timestamp": (float(x.get("timestamp") or 0) / 1000.0)} for x in (oi_raw if isinstance(oi_raw, list) else [])]
        ls = [{"ratio": x.get("longShortRatio"), "timestamp": (float(x.get("timestamp") or 0) / 1000.0)} for x in (ls_raw if isinstance(ls_raw, list) else [])]
        res = estimate(bars if isinstance(bars, list) else [], oi, ls)
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "note": f"дані недоступні ({type(exc).__name__}) — оцінку не будуємо"}
    if len(_EST_CACHE) > 100:
        _EST_CACHE.clear()
    _EST_CACHE[sym] = (time.time(), res)
    return res


_EST_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
