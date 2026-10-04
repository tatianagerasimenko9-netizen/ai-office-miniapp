#!/usr/bin/env python3
"""Незалежна звірка свічок знімка READY (gate.chart) з архівом Binance (data.binance.vision, USDT-M futures klines).

Використання:  python3 scripts/verify_snapshot_vs_archive.py <chart.json> [--samples 5]
chart.json — вміст gate.chart зі знімка. Архів за добу з'являється після її закінчення; для ще не закритої доби скрипт чесно каже «немає архіву».
Порівнюються open/high/low/close/volume свічок за тим самим open_time. Це контрольна перевірка, а не залежність системи."""
import argparse
import csv
import io
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

TOL = 1e-9


def compare(snapshot_candles, archive_rows, samples=5):
    """snapshot_candles: [[t,o,h,l,c,v]], archive_rows: {open_time_sec: (o,h,l,c,v)} → список розбіжностей за вибіркою свічок (рівномірно по діапазону, завжди включно з першою й останньою закритою)."""
    n = len(snapshot_candles)
    idx = sorted({0, max(0, n - 2)} | {int(i * (n - 1) / max(1, samples - 1)) for i in range(samples)})
    out = []
    for i in idx:
        row = snapshot_candles[i]
        t = round(float(row[0]))
        a = archive_rows.get(t)
        if a is None:
            out.append({"t": t, "status": "NO_ARCHIVE_ROW"})
            continue
        diffs = {k: (float(row[j + 1]), a[j]) for j, k in enumerate(("open", "high", "low", "close")) if abs(float(row[j + 1]) - a[j]) > TOL * max(1.0, abs(a[j]))}
        vol_diff = None if row[5] is None else (float(row[5]), a[4]) if abs(float(row[5]) - a[4]) > 1e-6 * max(1.0, abs(a[4])) else None
        out.append({"t": t, "status": "OK" if not diffs and vol_diff is None else "DIFF", "ohlc_diff": diffs, "volume_diff": vol_diff})
    return out


def fetch_archive_day(symbol, interval, day):
    url = f"https://data.binance.vision/data/futures/um/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{day}.zip"
    with urllib.request.urlopen(url, timeout=30) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    rows = {}
    for name in z.namelist():
        for rec in csv.reader(io.TextIOWrapper(z.open(name))):
            try:
                rows[round(int(rec[0]) / 1000.0)] = (float(rec[1]), float(rec[2]), float(rec[3]), float(rec[4]), float(rec[5]))
            except (ValueError, IndexError):
                continue   # заголовок
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chart")
    ap.add_argument("--samples", type=int, default=5)
    a = ap.parse_args()
    ch = json.load(open(a.chart))
    prov = ch.get("provenance") or {}
    sym, itv = prov.get("symbol"), ch.get("tf") or prov.get("interval")
    days = sorted({datetime.fromtimestamp(c[0], tz=timezone.utc).strftime("%Y-%m-%d") for c in ch["candles"]})
    arch = {}
    for d in days:
        try:
            arch.update(fetch_archive_day(sym, itv, d))
        except Exception as exc:  # noqa: BLE001
            print(f"немає архіву за {d}: {type(exc).__name__}: {exc}")
    res = compare(ch["candles"], arch, a.samples)
    for r in res:
        print(r)
    bad = [r for r in res if r["status"] != "OK"]
    print("ЗБІГАЄТЬСЯ" if res and not bad else ("НЕМАЄ ДАНИХ" if not arch else f"РОЗБІЖНОСТІ: {len(bad)}"))
    return 0 if res and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
