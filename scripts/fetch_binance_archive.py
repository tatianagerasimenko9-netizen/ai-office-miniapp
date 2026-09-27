#!/usr/bin/env python3
"""Offline replay input from public Binance Vision USD-M monthly archives.

Uses real exchange OHLCV, validates every interval, never synthesizes gaps.
No credentials, Telegram, Worker or orders.
"""
import argparse
import csv
import io
import json
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
DUR = {"1d": 86400000, "1h": 3600000, "15m": 900000}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", choices=["BTCUSDT", "MANTAUSDT"], required=True)
    ap.add_argument("--month", required=True, help="YYYY-MM, completed month")
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    start = datetime.strptime(a.month, "%Y-%m").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if (start.year, start.month) >= (now.year, now.month):
        raise ValueError("only completed historical months are allowed")
    result = {"symbol": a.symbol, "source": f"Binance Vision USD-M monthly klines {a.month}", "timeframes": {}}
    for tf in DUR:
        filename = f"{a.symbol}-{tf}-{a.month}.zip"
        url = f"{BASE}/{a.symbol}/{tf}/{filename}"
        request = urllib.request.Request(url, headers={"User-Agent": "ai-office-offline-replay/1.0"})
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [n for n in archive.namelist() if n.endswith(".csv")]
            if len(names) != 1:
                raise ValueError(f"expected one CSV in {filename}")
            reader = csv.reader(io.TextIOWrapper(archive.open(names[0]), encoding="utf-8"))
            candles = []
            for row in reader:
                if not row or not row[0].isdigit():
                    continue
                opened = int(row[0])
                # Some newer archive files use microsecond timestamps.
                if opened > 10**14:
                    opened //= 1000
                candles.append({
                    "ts": datetime.fromtimestamp(opened / 1000, timezone.utc).isoformat(),
                    "open": float(row[1]), "high": float(row[2]),
                    "low": float(row[3]), "close": float(row[4]),
                    "volume": float(row[5]),
                })
        if not candles:
            raise ValueError(f"no real candles in {filename}")
        timestamps = [int(datetime.fromisoformat(c["ts"]).timestamp() * 1000) for c in candles]
        if timestamps[0] != int(start.timestamp() * 1000):
            raise ValueError(f"missing first {tf} candle")
        if any(b-a != DUR[tf] for a,b in zip(timestamps,timestamps[1:])):
            raise ValueError(f"gap or duplicate in {tf} archive")
        result["timeframes"][tf] = candles
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print("REAL_BINANCE_ARCHIVE", a.symbol, a.month,
          {tf: len(v) for tf,v in result["timeframes"].items()})


if __name__ == "__main__":
    main()
