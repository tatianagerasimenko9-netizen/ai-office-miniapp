"""Джерела «грошового потоку», яких немає у свічках (публічний архів Binance, лише читання):
  metrics (5 хв): open interest, top-trader long/short (рахунки й позиції), глобальний long/short, taker long/short volume ratio;
  fundingRate (monthly): ставка фандингу.
Усі значення, що використовуються в рішенні в момент t, беруться ЛИШЕ зі знімків не пізніше t − 300 с."""
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
from typing import Dict, List, Optional

import numpy as np

BASE = "https://data.binance.vision/data/futures/um"
SNAP_LAG = 300.0


def _get(url: str) -> Optional[bytes]:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "office2-research"}), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    return None


def parse_metrics_csv(text: str) -> np.ndarray:
    """Колонки результату: t, oi, oi_val, top_acct, top_pos, glob, taker. Порожні/некоректні рядки пропускаються."""
    rows: List[List[float]] = []
    for rec in csv.reader(io.StringIO(text)):
        if not rec or rec[0] == "create_time":
            continue
        try:
            t = datetime.strptime(rec[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            rows.append([t, float(rec[2]), float(rec[3]), float(rec[4]), float(rec[5]), float(rec[6]), float(rec[7])])
        except (ValueError, IndexError):
            continue
    return np.array(rows, dtype=np.float64).reshape(-1, 7)


def parse_funding_csv(text: str) -> np.ndarray:
    rows: List[List[float]] = []
    for rec in csv.reader(io.StringIO(text)):
        if not rec or rec[0] == "calc_time":
            continue
        try:
            rows.append([float(rec[0]) / 1000.0, float(rec[2])])
        except (ValueError, IndexError):
            continue
    return np.array(rows, dtype=np.float64).reshape(-1, 2)


def _day_metrics(symbol: str, day: datetime, cache: Path, offline: bool) -> Optional[np.ndarray]:
    name = f"{symbol}-metrics-{day:%Y-%m-%d}"
    cp, miss = cache / f"{name}.npy", cache / f"{name}.404"
    if cp.exists():
        return np.load(cp)
    if miss.exists() or offline:
        return None
    data = _get(f"{BASE}/daily/metrics/{urllib.parse.quote(symbol)}/{name}.zip")
    if data is None:
        miss.write_text("404")
        return None
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        arr = parse_metrics_csv(z.open(z.namelist()[0]).read().decode("utf-8", "replace"))
    np.save(cp, arr)
    return arr


def _month_funding(symbol: str, y: int, m: int, cache: Path, offline: bool) -> Optional[np.ndarray]:
    name = f"{symbol}-fundingRate-{y}-{m:02d}"
    cp, miss = cache / f"{name}.npy", cache / f"{name}.404"
    if cp.exists():
        return np.load(cp)
    if miss.exists() or offline:
        return None
    data = _get(f"{BASE}/monthly/fundingRate/{urllib.parse.quote(symbol)}/{name}.zip")
    if data is None:
        miss.write_text("404")
        return None
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        arr = parse_funding_csv(z.open(z.namelist()[0]).read().decode("utf-8", "replace"))
    np.save(cp, arr)
    return arr


def _rolling_std(x: np.ndarray, n: int) -> np.ndarray:
    """Ковзне std за ПОПЕРЕДНІ n значень (включно з поточним), NaN ігноруються; вимагає ≥ n/4 валідних."""
    v = np.where(np.isnan(x), 0.0, x)
    ok = (~np.isnan(x)).astype(float)
    c1, c2, cn = np.cumsum(v), np.cumsum(v * v), np.cumsum(ok)
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        j = i - n
        s1 = c1[i] - (c1[j] if j >= 0 else 0.0)
        s2 = c2[i] - (c2[j] if j >= 0 else 0.0)
        k = cn[i] - (cn[j] if j >= 0 else 0.0)
        if k >= max(n // 4, 10):
            m = s1 / k
            out[i] = np.sqrt(max(s2 / k - m * m, 0.0))
    return out


def prep(m: np.ndarray, fund: np.ndarray) -> Dict[str, np.ndarray]:
    """Складає масиви й похідні (зміни OI за 1 і 4 год та їхнє ковзне std за 7 діб — лише з минулого)."""
    order = np.argsort(m[:, 0], kind="stable")
    m = m[order]
    t = m[:, 0]
    d: Dict[str, np.ndarray] = {"t": t, "oi": m[:, 1], "top_acct": m[:, 3], "top_pos": m[:, 4], "glob": m[:, 5], "taker": m[:, 6]}
    for hh in (1, 4):
        j = np.searchsorted(t, t - hh * 3600.0, side="left")
        ok = (np.abs(t[np.clip(j, 0, len(t) - 1)] - (t - hh * 3600.0)) <= 600.0) & (j < np.arange(len(t)))
        chg = np.where(ok, m[:, 1] / np.maximum(m[np.clip(j, 0, len(t) - 1), 1], 1e-12) - 1.0, np.nan)
        d[f"oi_chg_{hh}"] = chg
        d[f"oi_std_{hh}"] = _rolling_std(chg, 2016)
        d[f"back_{hh}"] = j
    if len(fund):
        fo = np.argsort(fund[:, 0], kind="stable")
        d["fund_t"], d["fund_r"] = fund[fo, 0], fund[fo, 1]
    else:
        d["fund_t"], d["fund_r"] = np.array([]), np.array([])
    return d


def load_flow(symbol: str, d0: datetime, d1: datetime, cache: Path, offline: bool = False, workers: int = 6) -> Optional[Dict[str, np.ndarray]]:
    cache.mkdir(parents=True, exist_ok=True)
    days: List[datetime] = []
    d = d0
    while d <= d1:
        days.append(d)
        d += timedelta(days=1)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(lambda x: _day_metrics(symbol, x, cache, offline), days))
    good = [p for p in parts if p is not None and len(p)]
    if len(good) < 0.8 * len(days):
        return None
    months = sorted({(x.year, x.month) for x in days} | {((d0 - timedelta(days=40)).year, (d0 - timedelta(days=40)).month)})
    fparts = [_month_funding(symbol, y, m, cache, offline) for y, m in months]
    fund = np.vstack([p for p in fparts if p is not None and len(p)]) if any(p is not None and len(p) for p in fparts) else np.zeros((0, 2))
    return prep(np.vstack(good), fund)


def features(fl: Dict[str, np.ndarray], t_dec: float, sg: float, r4_rel: float) -> Dict[str, float]:
    """Decision-time ознаки потоку у ТЕРМІНАХ НАПРЯМУ УГОДИ (sg=+1 LONG, −1 SHORT). Знімок не пізніше t_dec − 300 с. r4_rel — зміна ціни за 4 год у напрямі угоди (ATR)."""
    t = fl["t"]
    nan = float("nan")
    out = {k: nan for k in ("oi_chg_1h_z", "oi_chg_4h_z", "oi_chg_24h", "oi_with_trend", "top_pos_rel", "top_acct_rel", "glob_rel", "d_top_pos_4h", "d_glob_4h", "taker_rel", "taker_rel_1h", "funding_rel", "funding_z")}
    i = int(np.searchsorted(t, t_dec - SNAP_LAG, side="right")) - 1
    if i < 0 or t_dec - SNAP_LAG - t[i] > 900.0:
        return out
    for hh in (1, 4):
        c, s = fl[f"oi_chg_{hh}"][i], fl[f"oi_std_{hh}"][i]
        if c == c and s == s and s > 1e-9:
            out[f"oi_chg_{hh}h_z"] = float(np.clip(c / s, -6, 6))
    j24 = int(np.searchsorted(t, t[i] - 86400.0, side="left"))
    if abs(t[j24] - (t[i] - 86400.0)) <= 900.0 and j24 < i:
        out["oi_chg_24h"] = float(fl["oi"][i] / max(fl["oi"][j24], 1e-12) - 1.0)
    z4 = out["oi_chg_4h_z"]
    if z4 == z4:
        out["oi_with_trend"] = float(np.sign(r4_rel) * z4)
    ln = lambda x: float(np.log(max(x, 1e-6)))
    out["top_pos_rel"] = sg * ln(fl["top_pos"][i])
    out["top_acct_rel"] = sg * ln(fl["top_acct"][i])
    out["glob_rel"] = sg * ln(fl["glob"][i])
    j4 = int(np.searchsorted(t, t[i] - 4 * 3600.0, side="left"))
    if abs(t[j4] - (t[i] - 4 * 3600.0)) <= 900.0 and j4 < i:
        out["d_top_pos_4h"] = sg * (ln(fl["top_pos"][i]) - ln(fl["top_pos"][j4]))
        out["d_glob_4h"] = sg * (ln(fl["glob"][i]) - ln(fl["glob"][j4]))
    out["taker_rel"] = sg * ln(fl["taker"][i])
    k0 = max(i - 11, 0)
    out["taker_rel_1h"] = sg * float(np.mean(np.log(np.maximum(fl["taker"][k0:i + 1], 1e-6))))
    ft, fr = fl["fund_t"], fl["fund_r"]
    if len(ft):
        k = int(np.searchsorted(ft, t_dec - SNAP_LAG, side="right")) - 1
        if k >= 0 and t_dec - ft[k] < 12 * 3600.0:
            out["funding_rel"] = float(sg * fr[k] * 1e4)
            hist = fr[max(k - 90, 0):k + 1]
            if len(hist) >= 20:
                # funding часто «прилипає» до базової ставки (std=0): відсутність варіації = нейтральний z=0, а не відсутнє значення
                out["funding_z"] = float(np.clip(sg * (fr[k] - hist.mean()) / hist.std(), -6, 6)) if hist.std() > 1e-9 else 0.0
    return out


FLOW_BLOCKS = {
    "OI": ("oi_chg_1h_z", "oi_chg_4h_z", "oi_chg_24h", "oi_with_trend"),
    "POS": ("top_pos_rel", "top_acct_rel", "glob_rel", "d_top_pos_4h", "d_glob_4h", "funding_rel", "funding_z"),
    "TAKER5": ("taker_rel", "taker_rel_1h"),
}
