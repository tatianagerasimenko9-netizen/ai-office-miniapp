"""Один WebSocket-потік `!miniTicker@arr` замість сотень REST-запитів `ticker/24hr` по одній монеті.

Вимір на production (worker, 7 хв після deploy #113): із 664 запитів до fapi 376 (57%, ≈54/хв) — `ticker/24hr` по одній монеті (зміна за добу, 24h high/low,
оцінка ліквідацій, обсяг). Потік miniTicker віддає ці самі поля для УСІХ монет раз на секунду одним з'єднанням: він не входить до ліміту потоків свічок
(OFFICE_WS_MAX_STREAMS не змінюється). Немає даних / потік мовчить → споживач іде тим самим REST, що й раніше.
Увімкнення: OFFICE_WS_TICKER=1 (за замовчуванням ВИМКНЕНО до окремого дозволу)."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from typing import Any, Dict, Optional

_LOCK = threading.Lock()
_TICK: Dict[str, Dict[str, float]] = {}
_STATE: Dict[str, Any] = {"thread": None, "connected": False, "msgs": 0, "hits": 0, "misses": 0, "errors": 0, "last_msg": 0.0, "connects": 0, "last_error": None}
MAX_AGE_SEC = 30.0
_WATCH: Dict[str, Dict[int, list]] = {}      # символ під супроводом READY → {хвилина(unix): [open, high, low, close]} за ціною потоку; запасне джерело, коли REST Binance мовчить (429/418)
_WATCH_SINCE: Dict[str, float] = {}
WATCH_KEEP_MIN = 600
_MISS: Dict[str, Any] = {"symbol_missing": 0, "stale": 0, "no_open": 0, "ages": [], "stale_syms": {}}   # вимір причин промахів (лише облік, поведінку не змінює)
_MISS_AGES_CAP = 4000


def enabled() -> bool:
    return os.getenv("OFFICE_WS_TICKER", "0").strip() == "1"


def _base() -> str:
    return os.getenv("OFFICE_WS_BASE", "wss://fstream.binance.com/market/stream").strip()


def _log(msg: str) -> None:
    try:
        print(f"[ws-ticker] {msg}", flush=True)
    except Exception:  # noqa: BLE001
        pass


def _parse(data: Any) -> int:
    """Приймає і «сирий» масив, і обгортку {stream, data}; повертає, скільки монет оновлено."""
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return 0
    now = time.time()
    n = 0
    with _LOCK:
        for r in rows:
            if not isinstance(r, dict) or not r.get("s"):
                continue
            try:
                c, o, h, l_ = float(r["c"]), float(r["o"]), float(r["h"]), float(r["l"])
                q = float(r.get("q") or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            sym_u = str(r["s"]).upper()
            _TICK[sym_u] = {"c": c, "o": o, "h": h, "l": l_, "q": q, "at": now}
            n += 1
            wb = _WATCH.get(sym_u)
            if wb is not None:
                m = int(now // 60) * 60
                b = wb.get(m)
                if b is None:
                    wb[m] = [c, c, c, c]
                    for old in [k for k in wb if k < m - WATCH_KEEP_MIN * 60]:
                        wb.pop(old, None)
                else:
                    b[1] = max(b[1], c)
                    b[2] = min(b[2], c)
                    b[3] = c
        if n:
            _STATE["last_msg"] = now
    return n


def watch(symbol: str) -> None:
    """Ставить символ активного READY на запасний облік хвилинних барів із потоку (ціна останньої угоди ф'ючерсів). Нічого не робить, якщо потік вимкнено."""
    if not enabled():
        return
    sym = str(symbol or "").upper().strip()
    if not sym:
        return
    _ensure_thread()
    with _LOCK:
        if sym not in _WATCH:
            _WATCH[sym] = {}
            _WATCH_SINCE[sym] = time.time()


def watched_bars(symbol: str, since_ts: float = 0.0) -> list:
    """Хвилинні бари з потоку (лише ПОВНІ хвилини після початку спостереження за символом і після since_ts), формат як у свічок: ts, open, high, low, close. Порожньо — даних потоку немає."""
    sym = str(symbol or "").upper().strip()
    now = time.time()
    with _LOCK:
        wb = dict(_WATCH.get(sym) or {})
        t0 = _WATCH_SINCE.get(sym, now)
    out = []
    for m in sorted(wb):
        if m < t0 or m < since_ts or m + 60 > now:
            continue
        o, h, l_, c = wb[m]
        out.append({"ts": m, "open": o, "high": h, "low": l_, "close": c, "volume": 0.0, "src": "binance_futures"})
    return out


def get(symbol: str, max_age: float = MAX_AGE_SEC) -> Optional[Dict[str, float]]:
    """Те саме, що віддавав REST ticker/24hr (lastPrice, highPrice, lowPrice, quoteVolume, priceChangePercent), або None."""
    if not enabled():
        return None
    _ensure_thread()
    sym = str(symbol or "").upper().strip()
    if sym and not sym.endswith("USDT"):
        sym += "USDT"
    with _LOCK:
        r = _TICK.get(sym)
        if not r or time.time() - r["at"] > max_age or not r["o"]:
            _STATE["misses"] += 1
            if not r:
                _MISS["symbol_missing"] += 1
            elif not r["o"]:
                _MISS["no_open"] += 1
            else:
                _MISS["stale"] += 1
                if len(_MISS["ages"]) < _MISS_AGES_CAP:
                    _MISS["ages"].append(time.time() - r["at"])
                if len(_MISS["stale_syms"]) < 50 or sym in _MISS["stale_syms"]:
                    _MISS["stale_syms"][sym] = _MISS["stale_syms"].get(sym, 0) + 1
            return None
        _STATE["hits"] += 1
        return {"lastPrice": r["c"], "highPrice": r["h"], "lowPrice": r["l"], "quoteVolume": r["q"], "openPrice": r["o"],
                "priceChangePercent": (r["c"] / r["o"] - 1.0) * 100.0}


async def _session() -> None:
    import aiohttp

    url = f"{_base()}?streams=!miniTicker@arr"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=15)) as sess:
        async with sess.ws_connect(url, heartbeat=20.0, max_msg_size=0) as ws:
            with _LOCK:
                _STATE.update(connected=True)
                _STATE["connects"] += 1
            _log(f"підключено {url.split('?')[0]}")
            try:
                async for m in ws:
                    if m.type == aiohttp.WSMsgType.TEXT:
                        try:
                            with _LOCK:
                                _STATE["msgs"] += 1
                            _parse(json.loads(m.data))
                        except ValueError:
                            continue
                    elif m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                        break
            finally:
                with _LOCK:
                    _STATE["connected"] = False


def _thread_main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run() -> None:
        backoff = 1.0
        while True:
            t0 = time.time()
            try:
                await _session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                with _LOCK:
                    _STATE["errors"] += 1
                    _STATE["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
            await asyncio.sleep(backoff)
            backoff = 1.0 if time.time() - t0 > 60.0 else min(backoff * 2, 120.0)

    try:
        loop.run_until_complete(_run())
    except Exception:  # noqa: BLE001
        pass


def _ensure_thread() -> None:
    with _LOCK:
        t = _STATE["thread"]
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=_thread_main, name="ws-ticker", daemon=True)
        _STATE["thread"] = t
    t.start()


def _pct(a: list, q: float) -> Optional[float]:
    if not a:
        return None
    b = sorted(a)
    return round(b[min(len(b) - 1, int(q * len(b)))], 1)


def stats() -> Dict[str, Any]:
    with _LOCK:
        ages = list(_MISS["ages"])
        top = sorted(_MISS["stale_syms"].items(), key=lambda kv: -kv[1])[:5]
        return {"enabled": enabled(), "symbols": len(_TICK), **{k: _STATE[k] for k in ("connected", "connects", "msgs", "hits", "misses", "errors", "last_error")},
                "silent_sec": round(time.time() - _STATE["last_msg"], 1) if _STATE["last_msg"] else None,
                "miss_why": {"symbol_missing": _MISS["symbol_missing"], "stale": _MISS["stale"], "no_open": _MISS["no_open"],
                             "stale_age_s": {"p50": _pct(ages, 0.5), "p90": _pct(ages, 0.9), "p95": _pct(ages, 0.95), "max": round(max(ages), 1) if ages else None},
                             "stale_top": top}}


def reset_for_tests() -> None:
    _WATCH.clear()
    _WATCH_SINCE.clear()
    with _LOCK:
        _TICK.clear()
        _STATE.update(msgs=0, hits=0, misses=0, errors=0, last_msg=0.0, connects=0, connected=False, last_error=None)
        _MISS.update(symbol_missing=0, stale=0, no_open=0, ages=[], stale_syms={})
