"""T7: фактичні ліквідації BTCUSDT з Binance Futures forceOrder.

Це потік уже відбутих примусових ордерів, не прогнозна heatmap
і не «магніти» ліквідності. Дані не створюють ENTER / позиції / ордери.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

# Офіційний Futures combined-stream endpoint, один символ.
FORCE_ORDER_WS_URL = "wss://fstream.binance.com/ws/btcusdt@forceOrder"
FORCE_ORDER_SYMBOL = "BTCUSDT"
BUCKET_USD = 50.0
WS_FRESH_SEC = 180.0
EVENT_WINDOW_SEC = 3600.0
MAX_EVENTS = 2000
MAX_DEDUP = 4000
RECONNECT_BASE_SEC = 1.0
RECONNECT_MAX_SEC = 60.0
TOP_BUCKETS = 6

# Жорсткий прапор для тестів: шар не є джерелом сигналу.
CREATES_ENTER = False
CREATES_POSITION = False
CREATES_ORDER = False


def next_reconnect_delay(attempt: int) -> float:
    """Експоненційний backoff між reconnect."""
    n = max(0, int(attempt))
    delay = RECONNECT_BASE_SEC * (2 ** min(n, 8))
    return float(min(RECONNECT_MAX_SEC, delay))


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return None
    return x


def _i(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def liquidation_kind(side: str) -> str:
    """SELL = ліквідація лонгів; BUY = ліквідація шортів."""
    s = str(side or "").upper().strip()
    if s == "SELL":
        return "LONG_LIQ"
    if s == "BUY":
        return "SHORT_LIQ"
    return "UNKNOWN"


def event_dedup_key(ev: Dict[str, Any]) -> str:
    return (
        f"{ev.get('ts_ms')}|{ev.get('symbol')}|{ev.get('side')}|"
        f"{ev.get('price')}|{ev.get('qty')}"
    )


def parse_force_order_message(raw: Any) -> Optional[Dict[str, Any]]:
    """Розбір payload `btcusdt@forceOrder`. None, якщо це не ліквідація."""
    msg = raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(msg, dict):
        return None
    if "data" in msg and isinstance(msg.get("data"), dict):
        msg = msg["data"]
    o = msg.get("o")
    if not isinstance(o, dict):
        return None
    et = str(msg.get("e") or "")
    if et and et != "forceOrder":
        return None
    symbol = str(o.get("s") or "").upper().strip()
    if symbol != FORCE_ORDER_SYMBOL:
        return None
    side = str(o.get("S") or "").upper().strip()
    if side not in ("BUY", "SELL"):
        return None
    price = _f(o.get("ap")) or _f(o.get("p"))
    qty = _f(o.get("z")) or _f(o.get("q")) or _f(o.get("l"))
    ts_ms = _i(o.get("T")) or _i(msg.get("E")) or 0
    if price is None or qty is None or price <= 0 or qty <= 0:
        return None
    kind = liquidation_kind(side)
    ev = {
        "symbol": symbol,
        "side": side,
        "kind": kind,
        "price": float(price),
        "qty": float(qty),
        "notional": float(price) * float(qty),
        "ts_ms": int(ts_ms or 0),
        "source": "binance_futures_forceOrder",
        "forecast": False,
        "heatmap": False,
    }
    ev["id"] = event_dedup_key(ev)
    return ev


def bucket_price(price: float, bucket_usd: float = BUCKET_USD) -> float:
    step = float(bucket_usd) if bucket_usd > 0 else BUCKET_USD
    return round(int(float(price) / step) * step, 2)


def aggregate_price_buckets(
    events: List[Dict[str, Any]],
    *,
    bucket_usd: float = BUCKET_USD,
    limit: int = TOP_BUCKETS,
) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[float, str], Dict[str, Any]] = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        price = _f(ev.get("price"))
        qty = _f(ev.get("qty")) or 0.0
        if price is None:
            continue
        kind = str(ev.get("kind") or liquidation_kind(str(ev.get("side") or "")))
        key = (bucket_price(price, bucket_usd), kind)
        row = groups.get(key)
        if row is None:
            row = {
                "bucket": key[0],
                "kind": kind,
                "count": 0,
                "qty": 0.0,
                "notional": 0.0,
            }
            groups[key] = row
        row["count"] = int(row["count"]) + 1
        row["qty"] = float(row["qty"]) + float(qty)
        row["notional"] = float(row["notional"]) + float(price) * float(qty)
    out = sorted(groups.values(), key=lambda r: float(r["notional"]), reverse=True)
    return out[: max(1, int(limit))]


class BtcForceOrderBook:
    """In-memory кільце подій з дедупом і мітками свіжості WS."""

    def __init__(self) -> None:
        self.events: Deque[Dict[str, Any]] = deque()
        self._seen: Deque[str] = deque()
        self._seen_set = set()
        self.connected = False
        self.last_ws_rx_mono: float = 0.0
        self.last_event_mono: float = 0.0
        self.last_error = ""
        self.reconnects = 0

    def mark_connecting(self) -> None:
        self.connected = False

    def mark_connected(self) -> None:
        self.connected = True
        self.last_error = ""
        self.touch_ws()

    def mark_disconnected(self, err: str = "") -> None:
        self.connected = False
        if err:
            self.last_error = str(err)[:300]
        self.reconnects += 1

    def touch_ws(self) -> None:
        self.last_ws_rx_mono = time.monotonic()

    def ws_fresh(self, now_mono: Optional[float] = None) -> bool:
        now = float(now_mono if now_mono is not None else time.monotonic())
        if self.last_ws_rx_mono <= 0:
            return False
        return (now - self.last_ws_rx_mono) <= WS_FRESH_SEC

    def ingest(self, ev: Optional[Dict[str, Any]], *, now_mono: Optional[float] = None) -> bool:
        if not ev:
            return False
        key = str(ev.get("id") or event_dedup_key(ev))
        if key in self._seen_set:
            return False
        self._seen.append(key)
        self._seen_set.add(key)
        while len(self._seen) > MAX_DEDUP:
            old = self._seen.popleft()
            self._seen_set.discard(old)
        stamp = float(now_mono if now_mono is not None else time.monotonic())
        row = dict(ev)
        row["id"] = key
        row["mono"] = stamp
        self.events.append(row)
        self.last_event_mono = stamp
        self._prune(stamp)
        return True

    def ingest_raw(self, raw: Any, *, now_mono: Optional[float] = None) -> bool:
        self.touch_ws()
        return self.ingest(parse_force_order_message(raw), now_mono=now_mono)

    def _prune(self, now_mono: float) -> None:
        cutoff = now_mono - EVENT_WINDOW_SEC
        while self.events and float(self.events[0].get("mono") or 0.0) < cutoff:
            self.events.popleft()
        while len(self.events) > MAX_EVENTS:
            self.events.popleft()

    def recent_events(self, now_mono: Optional[float] = None) -> List[Dict[str, Any]]:
        now = float(now_mono if now_mono is not None else time.monotonic())
        self._prune(now)
        return list(self.events)

    def snapshot(self, now_mono: Optional[float] = None) -> Dict[str, Any]:
        now = float(now_mono if now_mono is not None else time.monotonic())
        events = self.recent_events(now)
        buckets = aggregate_price_buckets(events)
        long_n = sum(1 for e in events if e.get("kind") == "LONG_LIQ")
        short_n = sum(1 for e in events if e.get("kind") == "SHORT_LIQ")
        notional = sum(float(e.get("notional") or 0.0) for e in events)
        last_ts_ms = max((int(e.get("ts_ms") or 0) for e in events), default=0)
        return {
            "label": "фактичні ліквідації",
            "not_forecast": True,
            "not_heatmap": True,
            "creates_enter": CREATES_ENTER,
            "symbol": FORCE_ORDER_SYMBOL,
            "source": "binance_futures_ws:btcusdt@forceOrder",
            "connected": bool(self.connected),
            "ws_fresh": self.ws_fresh(now),
            "reconnects": int(self.reconnects),
            "last_error": self.last_error,
            "count": len(events),
            "long_liq": long_n,
            "short_liq": short_n,
            "notional": round(notional, 4),
            "window_sec": EVENT_WINDOW_SEC,
            "bucket_usd": BUCKET_USD,
            "buckets": buckets,
            "last_event_ts_ms": last_ts_ms,
        }


def format_radar_liq_summary(book: BtcForceOrderBook, *, now_mono: Optional[float] = None) -> str:
    """Коротке зведення для радара. Не картка входу."""
    snap = book.snapshot(now_mono)
    lines = [
        "Фактичні ліквідації BTCUSDT (Binance forceOrder, не прогнозна heatmap):",
    ]
    if snap["connected"] and snap["ws_fresh"]:
        lines.append("Потік живий.")
    else:
        err = snap["last_error"] or "немає живого потоку"
        lines.append(f"Потік не свіжий ({err}). Це не сигнал і не магніт ліквідності.")
    if snap["count"] <= 0:
        lines.append(f"За вікно {int(EVENT_WINDOW_SEC // 60)} хв подій немає.")
        lines.append("Не вхід, не позиція, не ордер.")
        return "\n".join(lines)
    lines.append(
        f"За ~{int(EVENT_WINDOW_SEC // 60)} хв: {snap['count']} подій "
        f"(лонгів ліквідовано {snap['long_liq']}, шортів {snap['short_liq']}), "
        f"ноціонал ≈ {snap['notional']:.0f} USDT."
    )
    for b in snap["buckets"][:4]:
        kind_ua = "лонги" if b["kind"] == "LONG_LIQ" else "шорти"
        lines.append(
            f"діапазон ~{b['bucket']:.0f}: {kind_ua} ×{b['count']} "
            f"qty {b['qty']:.4g}"
        )
    lines.append("Це вже відбуті ліквідації, не прогноз майбутніх рівнів і не підстава для ENTER.")
    return "\n".join(lines)


BTC_FORCE_ORDER_BOOK = BtcForceOrderBook()


async def run_btc_force_order_loop(
    book: Optional[BtcForceOrderBook] = None,
    *,
    url: str = FORCE_ORDER_WS_URL,
    stop: Optional[asyncio.Event] = None,
) -> None:
    """WS-клієнт з reconnect. Лише збір; без торгових дій."""
    import aiohttp

    target = book if book is not None else BTC_FORCE_ORDER_BOOK
    attempt = 0
    while stop is None or not stop.is_set():
        target.mark_connecting()
        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=20, sock_read=90)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(url, heartbeat=20, autoclose=True) as ws:
                    attempt = 0
                    target.mark_connected()
                    async for msg in ws:
                        if stop is not None and stop.is_set():
                            await ws.close()
                            return
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            target.ingest_raw(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            target.ingest_raw(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSE,
                        ):
                            break
        except asyncio.CancelledError:
            target.mark_disconnected("cancelled")
            raise
        except Exception as exc:
            target.mark_disconnected(f"{type(exc).__name__}: {exc}")
        else:
            target.mark_disconnected("ws closed")
        if stop is not None and stop.is_set():
            return
        delay = next_reconnect_delay(attempt)
        attempt += 1
        if stop is None:
            await asyncio.sleep(delay)
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
