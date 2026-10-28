"""Regression: B&R must not let later fresh signals expire behind earlier card sends."""
from __future__ import annotations

import asyncio
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br import live


def test_fresh_signal_is_delivered_before_scanning_next_symbol(monkeypatch):
    events = []

    monkeypatch.setenv("BR_LIVE_TG", "1")
    monkeypatch.setenv("BR_LIVE_SYMBOLS", "BTCUSDT,ETHUSDT")
    monkeypatch.setenv("BR_LIVE_DYNAMIC_UNIVERSE", "0")
    bridge = types.ModuleType("office_bridge")
    bridge._execute = lambda *args, **kwargs: None
    market_data = types.ModuleType("office_market_data")
    market_data.hard_backoff_left = lambda: 0.0
    monkeypatch.setitem(sys.modules, "office_bridge", bridge)
    monkeypatch.setitem(sys.modules, "office_market_data", market_data)
    monkeypatch.setattr(live.store, "init", lambda *args, **kwargs: None)

    now = time.time()
    last_open = now - 960  # last closed M15 candle closed one minute ago
    bars = []
    for i in range(240):
        ts = last_open - (239 - i) * 900
        stamp = datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
        bars.append({"ts": stamp, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})

    def fetch(symbol, timeframe, limit, *, closed_only=True):
        return bars

    def scan_symbol(db, symbol, fetch_fn, now=None, *, htf_fetch=None):
        events.append(("scan", symbol))
        return 1

    async def deliver(db, send, send_image=None, fetch=None):
        events.append(("deliver",))
        return 1

    async def track(db, fetch, send):
        events.append(("track",))
        return 0

    async def stop_after_one_cycle(delay):
        if delay == 45:
            return
        raise asyncio.CancelledError()

    monkeypatch.setattr(live, "scan_symbol", scan_symbol)
    monkeypatch.setattr(live, "deliver", deliver)
    monkeypatch.setattr(live, "track", track)
    monkeypatch.setattr(live.asyncio, "sleep", stop_after_one_cycle)

    async def run_one_cycle():
        try:
            await live.monitor("read-only-test-db", lambda *a, **k: 1, fetch)
        except asyncio.CancelledError:
            pass

    asyncio.run(run_one_cycle())

    # Existing lifecycle tracking must run before any new symbol scan, so a
    # slow scan/card delivery cannot postpone an already-open signal's TP/SL.
    # Fresh candidates are still delivered after their own symbol scan; the final
    # drain retries pending deliveries at the end of the cycle.
    assert events[:5] == [
        ("track",),
        ("scan", "BTCUSDT"),
        ("deliver",),
        ("scan", "ETHUSDT"),
        ("deliver",),
    ]
    assert events[-1:] == [("deliver",)]
