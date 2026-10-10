#!/usr/bin/env python3
"""Історичні свічки Binance USDT-M Futures з публічного архіву data.binance.vision (без ключів, без rate limit біржі).
Використовується ізольованим replay (GitHub Actions), НЕ живим сервісом. Повертає масиви {t,o,h,l,c,v,tbv}, t — секунди відкриття UTC."""
from __future__ import annotations

import calendar
import csv
import io
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
BASE = "https://data.binance.vision/data/futures/um"
WIDTH = {"15m": 900, "1d": 86400}


def _get(url: str, tries: int = 4):
    for k in range(tries):
        try:
            with urlopen(Request(url, headers={"User-Agent": "ai-office-replay/1.0"}), timeout=40) as r:
                return r.read()
        except HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except (URLError, TimeoutError) as e:
            err = e
        time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"{url}: {err}")


def _parse(raw: bytes):
    z = zipfile.ZipFile(io.BytesIO(raw))
    rows = []
    for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8")):
        if not row or not row[0].strip().isdigit():
            continue                                  # заголовок
        t = float(row[0])
        t = t / 1e6 if t > 1e14 else t / 1e3          # мс (futures) або мкс
        rows.append((t, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), float(row[9])))
    return rows


def _months(d0: date, d1: date):
    y, m = d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def fetch(sym: str, interval: str, d0: date, d1: date, today: date = None) -> dict:
    """Свічки за [d0, d1] включно. Повні минулі місяці — місячними архівами, решта — добовими."""
    today = today or datetime.now(timezone.utc).date()
    jobs = []
    for y, m in _months(d0, d1):
        first, last = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
        if first >= d0 and last <= d1 and last < today - timedelta(days=2):
            jobs.append(f"{BASE}/monthly/klines/{sym}/{interval}/{sym}-{interval}-{y}-{m:02d}.zip")
        else:
            a, b = max(first, d0), min(last, d1)
            for k in range((b - a).days + 1):
                jobs.append(f"{BASE}/daily/klines/{sym}/{interval}/{sym}-{interval}-{(a + timedelta(days=k)).isoformat()}.zip")
    with ThreadPoolExecutor(8) as ex:
        parts = list(ex.map(_get, jobs))
    rows = [r for p in parts if p for r in _parse(p)]
    if not rows:
        return {}
    rows = sorted({r[0]: r for r in rows}.values())
    a = np.array(rows, dtype=float)
    return {"t": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4], "v": a[:, 5], "tbv": a[:, 6]}


def gaps(a: dict, width: int) -> int:
    return int((np.diff(a["t"]) > width * 1.5).sum()) if a else -1


def monthly_from_daily(d1: dict) -> dict:
    keys = [(datetime.fromtimestamp(t, timezone.utc).year, datetime.fromtimestamp(t, timezone.utc).month) for t in d1["t"]]
    idx, start = [], 0
    for i in range(1, len(keys) + 1):
        if i == len(keys) or keys[i] != keys[start]:
            idx.append((start, i))
            start = i
    t = [float(datetime(keys[s][0], keys[s][1], 1, tzinfo=timezone.utc).timestamp()) for s, e in idx]
    return {"t": np.array(t), "o": np.array([d1["o"][s] for s, e in idx]), "h": np.array([d1["h"][s:e].max() for s, e in idx]), "l": np.array([d1["l"][s:e].min() for s, e in idx]),
            "c": np.array([d1["c"][e - 1] for s, e in idx]), "v": np.array([d1["v"][s:e].sum() for s, e in idx]), "tbv": np.array([d1["tbv"][s:e].sum() for s, e in idx])}


def build_arrays(sym: str, end_day: date, days: int, warmup_days: int = 55, d1_days: int = 320) -> dict:
    """M15 за [end−days−warmup, end+2д], D1 за d1_days; H4/W1/MN — похідні (як у живому конвеєрі через F.resample)."""
    from office2 import features as F

    m15 = fetch(sym, "15m", end_day - timedelta(days=days + warmup_days), end_day + timedelta(days=2))
    d1 = fetch(sym, "1d", end_day - timedelta(days=d1_days), end_day + timedelta(days=2))
    if not m15 or not d1:
        return {}
    return {"m15": m15, "h4": F.resample(m15, 14400), "d1": d1, "w1": F.resample(d1, 604800, offset=F.WEEK_OFFSET), "mn": monthly_from_daily(d1),
            "quality": {"m15_bars": len(m15["t"]), "m15_gaps": gaps(m15, 900), "d1_bars": len(d1["t"]), "d1_gaps": gaps(d1, 86400),
                        "first": datetime.fromtimestamp(m15["t"][0], timezone.utc).isoformat(), "last": datetime.fromtimestamp(m15["t"][-1], timezone.utc).isoformat()}}


if __name__ == "__main__":
    s = sys.argv[1]
    a = build_arrays(s, date.fromisoformat(sys.argv[2]), int(sys.argv[3]))
    print(a.get("quality") if a else "немає даних")
