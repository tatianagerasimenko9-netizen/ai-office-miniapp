#!/usr/bin/env python3
"""Fetch *real* closed Binance USD-M historical OHLCV for offline PR68 replay.

Explicit manual command only; never runs on Worker, never places orders, never
creates synthetic candles. Output is an auditable local JSON input to T6.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://fapi.binance.com/fapi/v1/klines"
INTERVAL_MS = {"1d": 86400000, "1h": 3600000, "15m": 900000}


def download(symbol: str, interval: str, start_ms: int, end_ms: int):
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        params = urllib.parse.urlencode({
            "symbol": symbol, "interval": interval, "startTime": cursor,
            "endTime": end_ms - 1, "limit": 1500,
        })
        request = urllib.request.Request(API + "?" + params, headers={
            "User-Agent": "ai-office-pr68-offline-replay/1.0",
        })
        with urllib.request.urlopen(request, timeout=25) as response:
            batch = json.load(response)
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            opened = int(item[0])
            if opened < start_ms or opened + INTERVAL_MS[interval] > end_ms:
                continue
            rows.append({
                "ts": datetime.fromtimestamp(opened / 1000, tz=timezone.utc).isoformat(),
                "open": float(item[1]), "high": float(item[2]),
                "low": float(item[3]), "close": float(item[4]),
                "volume": float(item[5]),
            })
        next_cursor = int(batch[-1][0]) + INTERVAL_MS[interval]
        if next_cursor <= cursor:
            raise RuntimeError("non-progressing Binance kline pagination")
        cursor = next_cursor
        time.sleep(0.12)
    if not rows:
        raise RuntimeError(f"no real {symbol} {interval} candles in requested range")
    if any(int(datetime.fromisoformat(b["ts"]).timestamp() * 1000) -
           int(datetime.fromisoformat(a["ts"]).timestamp() * 1000) != INTERVAL_MS[interval]
           for a, b in zip(rows, rows[1:])):
        raise RuntimeError(f"gap in {symbol} {interval} candles; refusing incomplete replay")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=("BTCUSDT", "MANTAUSDT"), required=True)
    parser.add_argument("--start", required=True, help="UTC ISO 8601 inclusive")
    parser.add_argument("--end", required=True, help="UTC ISO 8601 exclusive")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("start/end must be timezone-aware and ordered")
    end_ms = int(end.timestamp() * 1000)
    if end_ms > int(time.time() * 1000):
        raise ValueError("end must be in the past: closed candles only")
    start_ms = int(start.timestamp() * 1000)
    data = {
        "symbol": args.symbol,
        "source": f"Binance USD-M {API}; UTC [{start.isoformat()}, {end.isoformat()})",
        "timeframes": {
            tf: download(args.symbol, tf, start_ms, end_ms)
            for tf in ("1d", "1h", "15m")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"REAL_OHLCV {args.symbol} {args.output} " +
          " ".join(f"{tf}={len(v)}" for tf, v in data["timeframes"].items()))


if __name__ == "__main__":
    main()
