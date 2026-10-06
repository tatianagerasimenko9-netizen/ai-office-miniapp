"""Завантаження 1m-свічок Binance USDT-M Futures з публічного архіву data.binance.vision (лише читання). Колонки: t,o,h,l,c,v,tbv (taker buy base volume)."""
from __future__ import annotations

import csv
import io
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

BASE = "https://data.binance.vision/data/futures/um/daily/klines"


def _fetch_day(symbol: str, day: datetime, cache: Path, offline: bool) -> Optional[np.ndarray]:
    name = f"{symbol}-1m-{day:%Y-%m-%d}"
    cp = cache / f"{name}.npy"
    miss = cache / f"{name}.404"
    if cp.exists():
        return np.load(cp)
    if miss.exists() or offline:
        return None
    url = f"{BASE}/{urllib.parse.quote(symbol)}/1m/{urllib.parse.quote(name)}.zip"
    data = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "office2-research"}), timeout=60) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                miss.write_text("404")
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    if data is None:
        return None
    rows: List[List[float]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        with z.open(z.namelist()[0]) as f:
            for rec in csv.reader(io.TextIOWrapper(f)):
                try:
                    t = float(rec[0])
                except ValueError:
                    continue
                t = t / 1000.0 if t > 1e11 else t
                rows.append([t, float(rec[1]), float(rec[2]), float(rec[3]), float(rec[4]), float(rec[5]), float(rec[9])])
    arr = np.array(rows, dtype=np.float64)
    np.save(cp, arr)
    return arr


def load_symbol(symbol: str, d0: datetime, d1: datetime, cache: Path, offline: bool = False, workers: int = 6) -> Tuple[Optional[Dict[str, np.ndarray]], List[str]]:
    cache.mkdir(parents=True, exist_ok=True)
    days: List[datetime] = []
    d = d0
    while d <= d1:
        days.append(d)
        d += timedelta(days=1)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(lambda x: _fetch_day(symbol, x, cache, offline), days))
    missing = [f"{x:%Y-%m-%d}" for x, p in zip(days, parts) if p is None or len(p) == 0]
    good = [p for p in parts if p is not None and len(p)]
    if not good:
        return None, missing
    a = np.concatenate(good)
    a = a[np.argsort(a[:, 0], kind="stable")]
    _, u = np.unique(a[:, 0], return_index=True)
    a = a[u]
    return {"t": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4], "v": a[:, 5], "tbv": a[:, 6]}, missing


def from_arrays(t, o, h, l, c, v, tbv) -> Dict[str, np.ndarray]:
    return {k: np.asarray(x, dtype=np.float64) for k, x in zip(("t", "o", "h", "l", "c", "v", "tbv"), (t, o, h, l, c, v, tbv))}
