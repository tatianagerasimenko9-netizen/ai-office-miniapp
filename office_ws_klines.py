"""Свічки Binance Futures через WebSocket (combined kline streams) замість опитування REST.

Навіщо: кожен REST-запит свічок їсть ліміт ваги IP, спільний з іншими сервісами. Тут — одне постійне з'єднання:
Binance сам шле оновлення свічок по підписаних потоках, ліміт запитів не витрачається.

Схема (лише для свічок офісу; ордерів немає):
  1. fetch_candles викликає `register(символ, ТФ)` → потік підписується (SUBSCRIBE, пачками, ≤ ~4 повідомлень/с).
  2. Історія завантажується ОДНИМ REST-запитом (з існуючим пейсингом/розгоном) і передається в `seed`.
     Seed приймається лише якщо підписка була підтверджена ДО початку REST-запиту — тоді між історією й потоком немає діри.
  3. Далі `get()` віддає свічки з пам'яті: закриті — з потоку, остання (формується) — оновлюється в реальному часі.
  4. Обрив з'єднання → всі накопичення скидаються (щоб не було дір), працює REST, потім свічки заново «засіваються».
Вмикається `OFFICE_WS_KLINES=1` (за замовчуванням вимкнено). Без WebSocket усе працює як раніше через REST.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_IV_SEC = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
           "6h": 21600, "8h": 28800, "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800}
_MAX_BARS = 1500              # ліміт історії Binance за один запит
_LOCK = threading.RLock()
_STORE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_STATE: Dict[str, Any] = {"connected": False, "connected_at": 0.0, "last_msg": 0.0, "connects": 0, "disconnects": 0,
                          "msgs": 0, "hits": 0, "misses": 0, "seeds": 0, "errors": 0, "last_error": None, "sub_errors": 0}
_THREAD: Optional[threading.Thread] = None
_HEARTBEAT = ("BTCUSDT", "1m")   # постійний потік: щохвилини десятки повідомлень — за ним бачимо, що з'єднання живе
_INFLIGHT: Dict[int, List[Tuple[str, str]]] = {}
_REQ_ID = 0
_IDLE_DROP_SEC = 1800.0       # потік, який ніхто не читав 30 хв, відписуємо (щоб не тримати зайве)
_BAD_SEC = 600.0              # символ, який Binance відхилив, 10 хв читаємо через REST


def enabled() -> bool:
    return os.getenv("OFFICE_WS_KLINES", "0").strip() == "1"


def _max_streams() -> int:
    try:
        return max(1, int(os.getenv("OFFICE_WS_MAX_STREAMS", "200")))
    except ValueError:
        return 200


def _base_url() -> str:
    return os.getenv("OFFICE_WS_BASE", "wss://fstream.binance.com/stream").strip()


def _stream(sym: str, tf: str) -> str:
    return f"{sym.lower()}@kline_{tf}"


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _new_entry(now: float, acked: bool = False) -> Dict[str, Any]:
    return {"bars": [], "seeded": False, "state": "acked" if acked else "new", "acked_at": now if acked else 0.0,
            "last_msg": 0.0, "seeded_at": 0.0, "last_read": now, "want": 0, "bad_until": 0.0, "solo": False, "first_ts": None}


def _ensure_thread() -> None:
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        _THREAD = threading.Thread(target=_thread_main, name="ws-klines", daemon=True)
        _THREAD.start()


def register(symbol: str, tf: str, want: int = 0) -> bool:
    """Заявка на потік (символ, ТФ). Повертає True, якщо потік відстежується (або вже чекає підписки)."""
    if not enabled() or str(tf) not in _IV_SEC:
        return False
    key = (str(symbol).upper(), str(tf))
    now = time.time()
    with _LOCK:
        e = _STORE.get(key)
        if e is None:
            if len(_STORE) >= _max_streams():
                return False
            e = _STORE[key] = _new_entry(now)
        if e["bad_until"] > now:
            return False
        e["last_read"] = now
        e["want"] = max(e["want"], int(want or 0))
    _ensure_thread()
    return True


def wanted_limit(symbol: str, tf: str) -> int:
    with _LOCK:
        e = _STORE.get((str(symbol).upper(), str(tf)))
        return int(e["want"]) if e else 0


def _fresh_enough(e: Dict[str, Any], now: float) -> bool:
    if not _STATE["connected"] or now - _STATE["last_msg"] > 45.0:
        return False
    # тихий потік (нема угод) не вважаємо мертвим одразу, але довго без жодного оновлення — не довіряємо, перечитаємо REST
    return now - max(e["last_msg"], e["seeded_at"]) <= 300.0


def get(symbol: str, tf: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    """Свічки з потоку або None (тоді читаємо REST)."""
    if not enabled():
        return None
    key = (str(symbol).upper(), str(tf))
    now = time.time()
    with _LOCK:
        e = _STORE.get(key)
        if e is None:
            return None
        e["last_read"] = now
        if (e["seeded"] and e["state"] == "acked" and len(e["bars"]) >= int(limit) and _fresh_enough(e, now)):
            _STATE["hits"] += 1
            return e["bars"][-int(limit):]
        _STATE["misses"] += 1
        return None


def needs_seed(symbol: str, tf: str) -> bool:
    """Потік підписаний, але історії ще нема (або замало) — час завантажити її REST-запитом."""
    with _LOCK:
        e = _STORE.get((str(symbol).upper(), str(tf)))
        return bool(e and e["state"] == "acked" and _STATE["connected"] and not e["seeded"])


def seed(symbol: str, tf: str, rows: List[Dict[str, Any]], started_at: float) -> bool:
    """Історія з REST → пам'ять. Лише якщо підписка підтверджена до початку запиту (інакше між історією й потоком може бути діра)."""
    if not rows:
        return False
    key = (str(symbol).upper(), str(tf))
    with _LOCK:
        e = _STORE.get(key)
        if e is None or e["state"] != "acked" or not e["acked_at"] or not _STATE["connected"]:
            return False
        if str(rows[-1].get("src") or "") != "binance_futures":
            return False   # резервні свічки (спот/Bybit) у потік не кладемо
        # діри між історією й потоком немає, якщо підписку підтверджено ДО запиту, АБО остання свічка історії — та сама, з якої почався потік
        # (потік шле повний стан свічки, що формується, тож вона перезапишеться свіжою)
        covered = e["acked_at"] <= started_at and _STATE["connected_at"] <= started_at
        same_bar = e["first_ts"] is not None and rows[-1]["ts"] == e["first_ts"]
        if not (covered or same_bar):
            return False
        merged = [dict(r) for r in rows][-_MAX_BARS:]
        for b in e["bars"]:   # оновлення, що прийшли під час запиту, новіші за REST
            if b["ts"] == merged[-1]["ts"]:
                merged[-1] = b
            elif b["ts"] > merged[-1]["ts"]:
                merged.append(b)
        e["bars"] = merged[-_MAX_BARS:]
        e["seeded"] = True
        e["seeded_at"] = time.time()
        _STATE["seeds"] += 1
        return True


def _apply(sym: str, tf: str, row: Dict[str, Any]) -> None:
    now = time.time()
    with _LOCK:
        e = _STORE.get((sym, tf))
        if e is None:
            return
        e["last_msg"] = now
        if e["first_ts"] is None:
            e["first_ts"] = row["ts"]
        bars = e["bars"]
        if not bars:
            bars.append(row)
        elif row["ts"] == bars[-1]["ts"]:
            bars[-1] = row
        elif row["ts"] > bars[-1]["ts"]:
            bars.append(row)
            if len(bars) > _MAX_BARS:
                del bars[: len(bars) - _MAX_BARS]
        if not e["seeded"] and len(bars) > 5:   # без seed буфер не росте безкінечно
            del bars[: len(bars) - 5]


def _parse_event(msg: Any) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    d = msg.get("data") if isinstance(msg, dict) and "data" in msg else msg
    if not isinstance(d, dict) or d.get("e") != "kline":
        return None
    k = d.get("k") or {}
    try:
        sym = str(k.get("s") or d.get("s")).upper()
        tf = str(k.get("i"))
        row = {"open": float(k["o"]), "high": float(k["h"]), "low": float(k["l"]), "close": float(k["c"]),
               "volume": float(k["v"]), "ts": _iso(int(k["t"])), "src": "binance_futures"}
    except (KeyError, TypeError, ValueError):
        return None
    return sym, tf, row


def _on_disconnect() -> None:
    """Після обриву буфери недовірені (могли пропустити свічки) — скидаємо; REST працює, потім знову seed."""
    with _LOCK:
        if _STATE["connected"]:
            _STATE["disconnects"] += 1
        _STATE["connected"] = False
        _INFLIGHT.clear()
        now = time.time()
        for key, e in list(_STORE.items()):
            e.update(bars=[], seeded=False, acked_at=0.0, first_ts=None)
            e["state"] = "bad" if (e["state"] == "bad" and e["bad_until"] > now) else "new"


def _on_reply(msg: Dict[str, Any]) -> None:
    rid = msg.get("id")
    now = time.time()
    with _LOCK:
        keys = _INFLIGHT.pop(rid, [])
        if "error" in msg and msg.get("error"):
            _STATE["sub_errors"] += 1
            _STATE["last_error"] = str(msg.get("error"))[:200]
            for key in keys:
                e = _STORE.get(key)
                if e is None:
                    continue
                if len(keys) > 1:      # Binance відхиляє весь запит через один поганий потік — перепідписуємо по одному
                    e["state"] = "new"
                    e["solo"] = True
                else:
                    e["bad_until"] = now + _BAD_SEC
                    e["state"] = "bad"
            return
        for key in keys:
            e = _STORE.get(key)
            if e is not None and e["state"] == "sent":
                e["state"] = "acked"
                e["acked_at"] = now


def _pending_subs() -> List[Tuple[str, str]]:
    now = time.time()
    with _LOCK:
        out = []
        for key, e in _STORE.items():
            if e["state"] == "bad" and e["bad_until"] <= now:
                e["state"] = "new"
            if e["state"] == "new":
                out.append(key)
        out.sort(key=lambda k: not _STORE[k]["solo"])   # спершу «одинаки»
        return out


async def _sender(ws: Any) -> None:
    global _REQ_ID
    last_gc = time.time()
    while True:
        keys = _pending_subs()
        if keys:
            with _LOCK:
                keys = [keys[0]] if _STORE[keys[0]]["solo"] else [k for k in keys if not _STORE[k]["solo"]][:40]
            with _LOCK:
                _REQ_ID += 1
                rid = _REQ_ID
                for k in keys:
                    _STORE[k]["state"] = "sent"
                _INFLIGHT[rid] = list(keys)
            await ws.send_str(json.dumps({"method": "SUBSCRIBE", "params": [_stream(*k) for k in keys], "id": rid}))
            await asyncio.sleep(0.3)   # Binance: ≤10 керуючих повідомлень/с — тримаємось далеко нижче
            continue
        if time.time() - last_gc > 60.0:
            last_gc = time.time()
            drop = []
            with _LOCK:
                for key, e in list(_STORE.items()):
                    if key != _HEARTBEAT and time.time() - e["last_read"] > _IDLE_DROP_SEC:
                        drop.append(key)
                        del _STORE[key]
                if drop:
                    _REQ_ID += 1
                    rid = _REQ_ID
            if drop:
                await ws.send_str(json.dumps({"method": "UNSUBSCRIBE", "params": [_stream(*k) for k in drop], "id": rid}))
        await asyncio.sleep(0.5)


async def _session() -> None:
    import aiohttp

    url = f"{_base_url()}?streams={_stream(*_HEARTBEAT)}"
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.ws_connect(url, heartbeat=20.0, max_msg_size=0) as ws:
            now = time.time()
            with _LOCK:
                _STATE.update(connected=True, connected_at=now, last_msg=now)
                _STATE["connects"] += 1
                _STORE.setdefault(_HEARTBEAT, _new_entry(now))
                hb = _STORE[_HEARTBEAT]
                hb.update(state="acked", acked_at=now)   # він у самій адресі підключення
            sender = asyncio.ensure_future(_sender(ws))
            try:
                async for m in ws:
                    if m.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(m.data)
                        except ValueError:
                            continue
                        with _LOCK:
                            _STATE["msgs"] += 1
                            _STATE["last_msg"] = time.time()
                        if isinstance(data, dict) and "id" in data and ("result" in data or "error" in data):
                            _on_reply(data)
                            continue
                        ev = _parse_event(data)
                        if ev:
                            _apply(*ev)
                    elif m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                        break
            finally:
                sender.cancel()


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
            _on_disconnect()
            await asyncio.sleep(backoff)
            backoff = 1.0 if time.time() - t0 > 60.0 else min(backoff * 2, 120.0)   # стабільна сесія → швидкий перепідйом; збої → подвоєння

    try:
        loop.run_until_complete(_run())
    except Exception:  # noqa: BLE001
        pass


def stats() -> Dict[str, Any]:
    with _LOCK:
        by = {"acked": 0, "seeded": 0, "bad": 0}
        for e in _STORE.values():
            by["acked"] += e["state"] == "acked"
            by["seeded"] += bool(e["seeded"])
            by["bad"] += e["state"] == "bad"
        return {"enabled": enabled(), **{k: _STATE[k] for k in ("connected", "connects", "disconnects", "msgs", "hits", "misses", "seeds", "errors", "sub_errors", "last_error")},
                "streams": len(_STORE), **by, "silent_sec": round(time.time() - _STATE["last_msg"], 1) if _STATE["last_msg"] else None}


def reset_for_tests() -> None:
    with _LOCK:
        _STORE.clear()
        _INFLIGHT.clear()
        _STATE.update(connected=False, connected_at=0.0, last_msg=0.0, connects=0, disconnects=0, msgs=0, hits=0, misses=0,
                      seeds=0, errors=0, last_error=None, sub_errors=0)
