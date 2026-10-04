#!/usr/bin/env python3
"""Чи є різниця у результаті READY залежно від власного руху монети ПРОТИ напряму в останні 30 хв (як у VVV і SYRUP: SHORT після ривку вгору).
Лише дані ДО моменту READY для ознаки; майбутнє — тільки для результату. Ф'ючерсні 1m (data.binance.vision, лише читання).
Результат: після входу (дотик ціни входу) що перше — TP1 чи SL (в одній хвилині — SL); горизонт до 24 год або кінця даних. Вибірка мала й корельована (кілька днів) — це напрям для перевірки, не доказ."""
import io
import json
import math
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np

B = "https://data.binance.vision/data/futures/um/daily/klines/"
plans = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "study/plans_ready.json"))
days = sorted({(datetime.fromtimestamp(p["t"], tz=timezone.utc) + timedelta(days=k)).strftime("%Y-%m-%d") for p in plans for k in (-1, 0, 1)})


def get(sym, day):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(f"{B}{sym}/1m/{sym}-1m-{day}.zip", headers={"User-Agent": "x"}), timeout=60).read()
        t = zipfile.ZipFile(io.BytesIO(raw)).read(zipfile.ZipFile(io.BytesIO(raw)).namelist()[0]).decode()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ln in t.splitlines():
        p = ln.split(",")
        if p and p[0].isdigit():
            out.append((int(p[0]) // 1000, float(p[2]), float(p[3]), float(p[4])))
    return out


def series(sym):
    with ThreadPoolExecutor(3) as ex:
        parts = list(ex.map(lambda d: get(sym, d), days))
    rows = sorted({r[0]: r for p in parts for r in p}.values())
    return np.array(rows, dtype=float) if rows else None


syms = sorted({p["s"] for p in plans} | {"BTCUSDT"})
with ThreadPoolExecutor(6) as ex:
    data = dict(zip(syms, ex.map(series, syms)))
print(f"[data] символів із даними: {sum(1 for v in data.values() if v is not None)} з {len(syms)}; планів {len(plans)}", flush=True)
btc = data["BTCUSDT"]


def px(a, t):
    if a is None:
        return None
    i = np.searchsorted(a[:, 0], t - 60, side="right") - 1   # остання ЗАКРИТА хвилина до t
    return (a[i, 3], i) if i >= 0 and a[i, 0] >= t - 600 else None


def atr15(a, i):
    # ATR 14 свічок по 15 хв з 1m до індексу i (лише минуле)
    seg = a[max(0, i - 15 * 15):i + 1]
    if len(seg) < 15 * 14:
        return None
    k = len(seg) // 15
    seg = seg[-k * 15:].reshape(k, 15, 4)
    hi, lo, cl = seg[:, :, 1].max(1), seg[:, :, 2].min(1), seg[:, -1, 3]
    tr = np.maximum(hi[1:] - lo[1:], np.maximum(abs(hi[1:] - cl[:-1]), abs(lo[1:] - cl[:-1])))
    return float(tr.mean() / cl[-1] * 100.0)


rows = []
for p in plans:
    a = data.get(p["s"])
    if a is None or btc is None:
        continue
    now = px(a, p["t"])
    then = px(a, p["t"] - 1800)
    bnow, bthen = px(btc, p["t"]), px(btc, p["t"] - 1800)
    if not (now and then and bnow and bthen):
        continue
    ret = (now[0] / then[0] - 1) * 100
    bret = (bnow[0] / bthen[0] - 1) * 100
    sign = 1.0 if p["d"] == "SHORT" else -1.0
    against = sign * ret                # >0: монета рухалась ПРОТИ угоди (SHORT після росту / LONG після падіння)
    rel_against = sign * (ret - bret)   # власний рух понад BTC
    at = atr15(a, now[1])
    # результат
    i0 = np.searchsorted(a[:, 0], p["t"], side="left")
    end = min(len(a), np.searchsorted(a[:, 0], p["t"] + 24 * 3600, side="right"))
    long_ = p["d"] == "LONG"
    filled = False
    res = "nofill"
    for j in range(i0, end):
        hi, lo = a[j, 1], a[j, 2]
        if not filled:
            if lo <= p["e"] <= hi:
                filled = True
            else:
                continue
        hit_sl = lo <= p["sl"] if long_ else hi >= p["sl"]
        hit_tp = hi >= p["tp1"] if long_ else lo <= p["tp1"]
        if hit_sl:
            res = "SL"
            break
        if hit_tp:
            res = "TP1"
            break
    else:
        res = "open" if filled else "nofill"
    rows.append({"s": p["s"], "d": p["d"], "t": p["t"], "ag": against, "rel": rel_against, "atr": at, "ag_atr": (against / at) if at else None, "res": res})
print(f"[study] планів із повними даними: {len(rows)}", flush=True)


def wilson(k, n, z=1.96):
    if n == 0:
        return (0, 0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def table(title, key, edges, filt=lambda r: True):
    print(f"\n=== {title} ===")
    sel = [r for r in rows if filt(r) and r[key] is not None]
    print(f"{'межі':<18}{'n':>5}{'увійшло':>9}{'TP1':>8}{'SL':>8}{'відкр.':>8}   TP1/(TP1+SL)   SL/(TP1+SL) [95% CI]")
    for lo, hi in zip(edges[:-1], edges[1:]):
        g = [r for r in sel if lo <= r[key] < hi]
        f = [r for r in g if r["res"] != "nofill"]
        tp = sum(1 for r in f if r["res"] == "TP1")
        sl = sum(1 for r in f if r["res"] == "SL")
        op = sum(1 for r in f if r["res"] == "open")
        d = tp + sl
        ci = wilson(sl, d)
        print(f"{lo:>6.1f}…{hi:<8.1f}{len(g):>5}{len(f):>9}{tp:>8}{sl:>8}{op:>8}   {(tp / d * 100 if d else float('nan')):>6.1f}%      {(sl / d * 100 if d else float('nan')):>6.1f}% [{ci[0] * 100:.0f}–{ci[1] * 100:.0f}]")


INF = 1e9
table("ВСІ: рух монети за 30 хв ПРОТИ угоди, у ATR(15m)", "ag_atr", [-INF, -1, 0, 1, 2, INF])
table("SHORT: той самий показник", "ag_atr", [-INF, -1, 0, 1, 2, INF], lambda r: r["d"] == "SHORT")
table("LONG: той самий показник", "ag_atr", [-INF, -1, 0, 1, 2, INF], lambda r: r["d"] == "LONG")
table("ВСІ: власний рух проти угоди ПОНАД BTC за 30 хв, у %", "rel", [-INF, -0.5, 0, 0.5, 1, INF])
print("\nVVV/SYRUP у цій вибірці (за 2 жовтня їх немає; див. brain_coin_probe для 4 жовтня).")
