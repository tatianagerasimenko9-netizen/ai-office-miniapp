#!/usr/bin/env python3
"""Порівняння джерел свічок для тих самих карток радара: Binance USDT-M ф'ючерси (futures/um) vs Binance Spot (spot) vs Bybit linear. Лише читання.
Мета — довести/спростувати гіпотезу, що різниця TIA d37a (21:30 у production vs 21:15 у replay) виникла через спотові/Bybit свічки в fallback.
Виводить: TIA 20:45–22:00 M15 по джерелах, перший бар закриття за inval_px, V0 з виправленою інвалідацією по кожному джерелу, і на 17 картках — де статус/час розійшовся."""
from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from office2 import radar_watch as RW  # noqa: E402

FIX = ROOT / "scripts" / "fixtures" / "radar_cards_filled_2026-10-11.json"
D37A = "W|O2|d37a39e701ba"
ARCH = {"futures": "https://data.binance.vision/data/futures/um/daily/klines/{s}/15m/{s}-15m-{d}.zip",
        "spot": "https://data.binance.vision/data/spot/daily/klines/{s}/15m/{s}-15m-{d}.zip"}
ARCH1 = {"futures": "https://data.binance.vision/data/futures/um/daily/klines/{s}/1m/{s}-1m-{d}.zip",
         "spot": "https://data.binance.vision/data/spot/daily/klines/{s}/1m/{s}-1m-{d}.zip"}


def _get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ai-office-provenance/1.0"}), timeout=60).read()


def _norm(ts):
    o = int(ts)
    return (o // 1000 if o > 10**14 else o) / 1000.0


def archive(kind, tmpl, sym, t0, t1):
    out, d, end = {}, datetime.fromtimestamp(t0, timezone.utc).date(), datetime.fromtimestamp(t1, timezone.utc).date()
    while d <= end:
        try:
            z = zipfile.ZipFile(io.BytesIO(_get(tmpl.format(s=sym, d=d.isoformat()))))
            for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8")):
                if r and r[0].isdigit():
                    ts = _norm(r[0])
                    out[ts] = {"ts": ts, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])}
        except Exception as exc:  # noqa: BLE001
            print(f"  {kind} {sym} {d}: {type(exc).__name__} {getattr(exc, 'code', '')}", flush=True)
        d += timedelta(days=1)
    return [out[k] for k in sorted(out)]


def bybit(sym, t0, t1):
    try:
        raw = json.loads(_get(f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval=15&start={int(t0*1000)}&end={int(t1*1000)}&limit=1000"))
        rows = (raw.get("result") or {}).get("list") or []
        return sorted(({"ts": int(r[0]) / 1000.0, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in rows), key=lambda x: x["ts"])
    except Exception as exc:  # noqa: BLE001
        print(f"  bybit {sym}: {type(exc).__name__} {getattr(exc, 'code', '')}", flush=True)
        return []


def hhmm(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M") if ts else "—"


def main():
    cards = json.loads(FIX.read_text(encoding="utf-8"))
    cards = cards if isinstance(cards, list) else cards["cards"]
    now = time.time()
    data = {}
    for sym in sorted({c["symbol"] for c in cards}):
        t0 = min(c["created_ts"] for c in cards if c["symbol"] == sym) - 3600
        data[sym] = {"futures": archive("futures", ARCH["futures"], sym, t0, now), "spot": archive("spot", ARCH["spot"], sym, t0, now), "bybit": bybit(sym, t0, now)}
    print("# Порівняння джерел свічок (futures/um vs spot vs bybit)\n")
    # --- TIA d37a
    c = next(x for x in cards if x["card_id"] == D37A)
    t_lo, t_hi = c["created_ts"] - 1800, c["created_ts"] + 3 * 3600
    print(f"## TIA d37a: inval_px={c['inval_px']} created={hhmm(c['created_ts'])} sent={hhmm(c.get('sent_ts'))} UTC\n")
    print("| бар (open UTC) | src | open | high | low | close | close<inval_px |\n|---|---|---|---|---|---|---|")
    for b0 in sorted({b["ts"] for s in data["TIAUSDT"].values() for b in s if t_lo <= b["ts"] <= t_hi}):
        for name in ("futures", "spot", "bybit"):
            b = next((x for x in data["TIAUSDT"][name] if x["ts"] == b0), None)
            if b:
                print(f"| {hhmm(b0)} | {name} | {b['open']} | {b['high']} | {b['low']} | {b['close']} | {'так' if b['close'] < c['inval_px'] else 'ні'} |")
    print("\n| джерело | барів | перше закриття нижче inval_px | час скасування UTC | V0 статус | V0 entry_ts |\n|---|---|---|---|---|---|")
    for name in ("futures", "spot", "bybit"):
        bars = [b for b in data["TIAUSDT"][name] if b["ts"] + 900 <= now]
        inv = RW.first_invalidation(c, bars, now)
        ev = RW.evaluate_card(dict(c), bars, now) if bars else None
        print(f"| {name} | {len(bars)} | {hhmm(inv['bar_ts']) + ' закрилась ' + str(inv['close']) if inv else '—'} | {hhmm(inv['ts']) if inv else '—'} | {ev['paper_status'] if ev else 'ДАНИХ_НЕМАЄ'} | {hhmm(ev['entry_ts']) if ev else '—'} |")
    # --- M1 TIA
    print("\n### M1 TIA навколо 21:00–21:30 (close vs inval_px)\n\n| хв UTC | futures close | spot close |\n|---|---|---|")
    day = datetime.fromtimestamp(c["created_ts"], timezone.utc).date().isoformat()
    m1 = {k: {b["ts"]: b for b in archive(k, ARCH1[k], "TIAUSDT", c["created_ts"], c["created_ts"])} for k in ("futures", "spot")}
    base = (c["created_ts"] // 900) * 900
    for t in sorted(m1["futures"]):
        if base <= t < base + 4 * 900 and (t - base) % 300 == 0 or (t % 900 == 840 and base <= t < base + 4 * 900):
            f, s = m1["futures"].get(t), m1["spot"].get(t)
            print(f"| {hhmm(t)} | {f['close'] if f else '—'} | {s['close'] if s else '—'} |")
    # --- 17 карток
    print("\n## 17 карток: V0 з інвалідацією за джерелом\n\n| картка | символ | futures | spot | bybit | розбіжність |\n|---|---|---|---|---|---|")
    diff = 0
    for c in cards:
        cells, keys = [], []
        for name in ("futures", "spot", "bybit"):
            bars = [b for b in data[c["symbol"]][name] if b["ts"] + 900 <= now]
            if not bars:
                cells.append("ДАНИХ_НЕМАЄ")
                keys.append(None)
                continue
            ev = RW.evaluate_card(dict(c), bars, now)
            cells.append(f"{ev['paper_status']} {ev['r_net']} e={hhmm(ev['entry_ts'])} i={hhmm(ev.get('inval_ts'))}")
            keys.append((ev["paper_status"], ev["entry_ts"], ev.get("inval_ts")))
        real = [k for k in keys if k is not None]
        d = len(set(real)) > 1
        diff += d
        print(f"| {c['card_id'][-6:]} | {c['symbol']} | " + " | ".join(cells) + f" | {'ТАК' if d else 'ні'} |")
    print(f"\nКарток з розбіжністю між джерелами: {diff} з {len(cards)}.")


if __name__ == "__main__":
    main()
