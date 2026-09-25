#!/usr/bin/env python3
"""T7: фактичні ліквідації BTC — parse/dedup/buckets/freshness/reconnect; без ENTER."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_btc_liquidations import (  # noqa: E402
    BUCKET_USD,
    CREATES_ENTER,
    CREATES_ORDER,
    CREATES_POSITION,
    FORCE_ORDER_SYMBOL,
    BtcForceOrderBook,
    format_radar_liq_summary,
    next_reconnect_delay,
    parse_force_order_message,
    run_btc_force_order_loop,
)
from office_radar import evaluate_radar  # noqa: E402
from office_review_position import scanner_enter_opens_position  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402

SAMPLE_LONG = {
    "e": "forceOrder",
    "E": 1568014460893,
    "o": {
        "s": "BTCUSDT",
        "S": "SELL",
        "o": "LIMIT",
        "f": "IOC",
        "q": "0.014",
        "p": "9910",
        "ap": "9910",
        "X": "FILLED",
        "l": "0.014",
        "z": "0.014",
        "T": 1568014460893,
    },
}

SAMPLE_SHORT = {
    "e": "forceOrder",
    "E": 1568014461893,
    "o": {
        "s": "BTCUSDT",
        "S": "BUY",
        "o": "LIMIT",
        "f": "IOC",
        "q": "0.5",
        "p": "10040",
        "ap": "10040.2",
        "X": "FILLED",
        "l": "0.5",
        "z": "0.5",
        "T": 1568014461893,
    },
}


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0:
        return _fail("T0 ATR must stay 90")
    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("T1 ENTER still must not open position")
    if CREATES_ENTER or CREATES_POSITION or CREATES_ORDER:
        return _fail("liq layer must not create enter/position/order")

    ev = parse_force_order_message(json.dumps(SAMPLE_LONG))
    if not ev or ev["symbol"] != FORCE_ORDER_SYMBOL:
        return _fail("parse long")
    if ev["kind"] != "LONG_LIQ" or ev["side"] != "SELL":
        return _fail("SELL is long liquidation")
    if abs(ev["price"] - 9910.0) > 1e-9 or abs(ev["qty"] - 0.014) > 1e-9:
        return _fail("price/qty")
    if ev["forecast"] or ev["heatmap"]:
        return _fail("must not mark forecast/heatmap")

    wrapped = parse_force_order_message({"stream": "btcusdt@forceOrder", "data": SAMPLE_SHORT})
    if not wrapped or wrapped["kind"] != "SHORT_LIQ":
        return _fail("combined stream BUY is short liq")

    if parse_force_order_message({"e": "trade", "o": SAMPLE_LONG["o"]}) is not None:
        return _fail("non-forceOrder must drop")
    eth = json.loads(json.dumps(SAMPLE_LONG))
    eth["o"] = dict(eth["o"])
    eth["o"]["s"] = "ETHUSDT"
    if parse_force_order_message(eth) is not None:
        return _fail("only BTCUSDT")

    book = BtcForceOrderBook()
    t0 = 1_000_000.0
    if not book.ingest(ev, now_mono=t0):
        return _fail("first ingest")
    if book.ingest(ev, now_mono=t0 + 1):
        return _fail("duplicate must drop")
    if not book.ingest(wrapped, now_mono=t0 + 2):
        return _fail("second unique")
    snap = book.snapshot(t0 + 3)
    if snap["count"] != 2 or snap["long_liq"] != 1 or snap["short_liq"] != 1:
        return _fail(f"counts {snap}")
    if snap["creates_enter"] is not False or not snap["not_heatmap"]:
        return _fail("snapshot flags")
    if not snap["buckets"]:
        return _fail("buckets empty")
    if BUCKET_USD != 50.0:
        return _fail("bucket size")

    stale = BtcForceOrderBook()
    stale.ingest_raw(json.dumps(SAMPLE_LONG), now_mono=t0)
    stale.last_ws_rx_mono = t0
    if stale.ws_fresh(t0 + 181):
        return _fail("stale ws must fail freshness")
    if not stale.ws_fresh(t0 + 10):
        return _fail("fresh window")

    text = format_radar_liq_summary(book, now_mono=t0 + 3)
    low = text.lower()
    if "фактичн" not in low:
        return _fail("label actual")
    if "heatmap" not in low and "прогноз" not in low:
        return _fail("must deny heatmap/forecast")
    if "enter" in low and "не підстава для enter" not in low:
        return _fail("must not look like enter")
    if "WATCHING" in text or "SIGNAL" in text:
        return _fail("liq summary is not a radar status")

    if next_reconnect_delay(0) != 1.0:
        return _fail("backoff 0")
    if next_reconnect_delay(1) != 2.0:
        return _fail("backoff 1")
    if next_reconnect_delay(10) != 60.0:
        return _fail("backoff cap")

    # T6 evaluate_radar без цього шару — регресія статусів.
    daily = [
        {"open": 100, "high": 110, "low": 90, "close": 105},
        {"open": 105, "high": 110, "low": 90, "close": 100},
    ]
    # мінімум свічок радар ігнорує — NONE не стане SIGNAL від ліквідацій
    res = evaluate_radar(
        symbol="BTCUSDT",
        price=100.0,
        daily_candles=[],
        sweep_candles=[],
        m15_candles=[],
        utc_now=None,
    )
    if res.status == "SIGNAL":
        return _fail("empty candles must not SIGNAL")

    rc = asyncio.run(_ws_reconnect_case())
    if rc != 0:
        return rc
    print("OK T7 btc liquidations")
    return 0


async def _ws_reconnect_case() -> int:
    hits = {"n": 0}

    async def handler(request: web.Request) -> web.StreamResponse:
        hits["n"] += 1
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        if hits["n"] == 1:
            await ws.send_str(json.dumps(SAMPLE_LONG))
            await ws.send_str(json.dumps(SAMPLE_LONG))
            await ws.close()
            return ws
        await ws.send_str(json.dumps(SAMPLE_SHORT))
        await asyncio.sleep(0.2)
        return ws

    app = web.Application()
    app.router.add_get("/ws", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets if site._server else None
    port = sockets[0].getsockname()[1] if sockets else 0
    url = f"ws://127.0.0.1:{port}/ws"
    book = BtcForceOrderBook()
    stop = asyncio.Event()
    task = asyncio.create_task(run_btc_force_order_loop(book, url=url, stop=stop))
    deadline = asyncio.get_event_loop().time() + 8.0
    while asyncio.get_event_loop().time() < deadline:
        if book.snapshot()["count"] >= 2 and hits["n"] >= 2:
            break
        await asyncio.sleep(0.05)
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await runner.cleanup()
    snap = book.snapshot()
    if hits["n"] < 2:
        print(f"FAIL: reconnect did not happen hits={hits['n']}")
        return 1
    if snap["count"] != 2:
        print(f"FAIL: expected 2 unique after reconnect, got {snap}")
        return 1
    if book.reconnects < 1:
        print("FAIL: reconnects not counted")
        return 1
    print(f"OK ws local reconnect hits={hits['n']} count={snap['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
