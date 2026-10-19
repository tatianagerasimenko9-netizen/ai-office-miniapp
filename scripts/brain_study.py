#!/usr/bin/env python3
"""Дослідження Market Brain на історії БЕЗ look-ahead: які ознаки з'являлись за 15/30/60 хв ДО сильного руху BTC.

Дані (лише читання, безкоштовно, data.binance.vision): 1m свічки BTC/ETH (ф'ючерси), 5m свічки кошика, metrics (OI, співвідношення покупців/продавців) з кроком 5 хв,
funding. У кожен момент t ознаки рахуються тими самими функціями, що й у живому циклі (office_brain_features / office_market_brain), але ЛИШЕ з даних, доступних до t:
закриті свічки, OI і співвідношення із запізненням 5 хв, останній відомий funding. Майбутнє використовується тільки для мітки.
Мітка: за h хвилин після t ціна пройшла в один бік не менше K·σ (σ — стандартне відхилення 1m-змін за попередні 24 год × √h) і більше, ніж у протилежний.
Оцінка: частота руху після ознаки проти базової частоти (lift), окремо навчальна (перші ~8 міс.) і перевірочна (останні ~4 міс.) частини, довірчий інтервал блоками по дню.
Нічого не підганяється: пороги ознак — константи з модулів; тут лише вимірюємо. bookDepth, ліквідації, опціони в цій версії НЕ використано (див. висновок).
"""
import io
import json
import math
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_brain_features as bf  # noqa: E402
import office_market_brain as mb  # noqa: E402
import office_time_structure as tstruct  # noqa: E402

B = "https://data.binance.vision/data/futures/um/"
MONTHS = sys.argv[1].split(",") if len(sys.argv) > 1 else [f"2025-{m:02d}" for m in range(9, 13)] + [f"2026-{m:02d}" for m in range(1, 10)]
BASKET = ["ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "LTC", "TRX"]
HORIZONS = (15, 30, 60)
K = 2.0
STEP_MIN = 15


def fetch_zip(url, tries=3):
    for i in range(tries):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "brain-study"}), timeout=90).read()
            z = zipfile.ZipFile(io.BytesIO(raw))
            return z.read(z.namelist()[0]).decode()
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(1 + i)
    return None


def klines(sym, tf, months):
    def one(ym):
        t = fetch_zip(f"{B}monthly/klines/{sym}/{tf}/{sym}-{tf}-{ym}.zip")
        rows = []
        for ln in (t or "").splitlines():
            p = ln.split(",")
            if p and p[0].isdigit():
                rows.append((int(p[0]) // 1000, float(p[1]), float(p[2]), float(p[3]), float(p[4])))
        return rows
    with ThreadPoolExecutor(4) as ex:
        parts = list(ex.map(one, months))
    rows = sorted({r[0]: r for p in parts for r in p}.values())
    return np.array(rows, dtype=float) if rows else np.zeros((0, 5))


def metrics(sym, days):
    def one(d):
        t = fetch_zip(f"{B}daily/metrics/{sym}/{sym}-metrics-{d}.zip")
        out = []
        for ln in (t or "").splitlines():
            p = ln.split(",")
            if len(p) >= 8 and p[0][:2] == "20":
                try:
                    ts = datetime.strptime(p[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
                    out.append((ts, float(p[2]), float(p[6])))
                except ValueError:
                    pass
        return out
    with ThreadPoolExecutor(8) as ex:
        parts = list(ex.map(one, days))
    return sorted({r[0]: r for p in parts for r in p}.values())


def funding(sym, months):
    out = []
    for ym in months:
        t = fetch_zip(f"{B}monthly/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip")
        for ln in (t or "").splitlines():
            p = ln.split(",")
            if p and p[0].isdigit():
                out.append((int(p[0]) / 1000.0, float(p[2]) * 100.0))
    return sorted(out)


def agg(a, sec):
    """1m → свічки sec секунд (лише повні)."""
    if len(a) == 0:
        return a
    k = (a[:, 0] // sec).astype(np.int64)
    idx = np.flatnonzero(np.diff(k)) + 1
    starts = np.r_[0, idx]
    ends = np.r_[idx, len(a)]
    out = []
    per = sec // 60
    for s, e in zip(starts, ends):
        if e - s == per:
            out.append((k[s] * sec, a[s, 1], a[s:e, 2].max(), a[s:e, 3].min(), a[e - 1, 4]))
    return np.array(out, dtype=float)


def dicts(a, lo, hi):
    return [{"ts": datetime.fromtimestamp(float(r[0]), tz=timezone.utc).isoformat(), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in a[lo:hi]]


def main():
    t0 = time.time()
    btc1 = klines("BTCUSDT", "1m", MONTHS)
    eth1 = klines("ETHUSDT", "1m", MONTHS)
    print(f"[data] BTC 1m {len(btc1)} рядків, ETH 1m {len(eth1)}, {time.time() - t0:.0f} с", flush=True)
    first = datetime.fromtimestamp(btc1[0, 0], tz=timezone.utc)
    last = datetime.fromtimestamp(btc1[-1, 0], tz=timezone.utc)
    days = [(first + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((last - first).days + 1)]
    met = metrics("BTCUSDT", days)
    fund = funding("BTCUSDT", MONTHS)
    print(f"[data] metrics {len(met)} точок, funding {len(fund)}, {time.time() - t0:.0f} с", flush=True)
    bask = {}
    for s in BASKET:
        if s == "ETH":
            continue
        a = klines(s + "USDT", "5m", MONTHS)
        if len(a):
            bask[s] = {int(r[0]): r[4] for r in a}
    eth_c = {int(r[0]): r[4] for r in agg(eth1, 300)}
    bask["ETH"] = eth_c
    print(f"[data] кошик {len(bask)} монет, {time.time() - t0:.0f} с", flush=True)

    c5, c15, d1 = agg(btc1, 300), agg(btc1, 900), agg(btc1, 86400)
    e15 = agg(eth1, 900)
    ts1 = btc1[:, 0]
    close1, high1, low1 = btc1[:, 4], btc1[:, 2], btc1[:, 3]
    # σ за попередні 24 год (1m-зміни)
    ret1 = np.r_[0.0, np.diff(close1) / close1[:-1]]
    cs, cs2 = np.cumsum(ret1), np.cumsum(ret1 ** 2)

    def sigma(i, W=1440):
        if i < W:
            return None
        n = W
        m = (cs[i] - cs[i - W]) / n
        v = (cs2[i] - cs2[i - W]) / n - m * m
        return math.sqrt(max(v, 0.0))

    oi_ts = np.array([m[0] + 300 for m in met])   # ознака доступна із запізненням 5 хв
    oi_v = np.array([m[1] for m in met])
    ls_v = np.array([m[2] for m in met])
    f_ts = np.array([f[0] for f in fund])
    f_v = np.array([f[1] for f in fund])

    start_i = 1440 * 35   # прогрів: тижні/місяці/σ
    samples = []
    mem = mb.new_memory()
    trans = []
    week_cache = {}
    ts_up = c15[:, 0]
    n_iter = 0
    for i in range(start_i, len(btc1) - max(HORIZONS) - 1, STEP_MIN):
        now = float(ts1[i] + 60.0)   # свічка i закрита в now
        # закриті свічки до now
        j5 = np.searchsorted(c5[:, 0], now - 300 + 1, side="right")
        j15 = np.searchsorted(c15[:, 0], now - 900 + 1, side="right")
        je = np.searchsorted(e15[:, 0], now - 900 + 1, side="right")
        jd = np.searchsorted(d1[:, 0], now - 86400 + 1, side="right")
        if j5 < 60 or j15 < 100 or jd < 40:
            continue
        day = int(now // 86400)
        if day not in week_cache:
            dd = dicts(d1, max(0, jd - 100), jd)
            px = float(close1[i])
            snap = tstruct.snapshot(now, px, dd)
            week_cache[day] = (dd, snap)
        dd, snap = week_cache[day]
        k = np.searchsorted(oi_ts, now, side="right")
        oi_hist = [{"ts": float(oi_ts[x]), "oi": float(oi_v[x])} for x in range(max(0, k - 14), k)]
        ls = float(ls_v[k - 1]) if k else None
        kf = np.searchsorted(f_ts, now, side="right")
        fu = float(f_v[kf - 1]) if kf else None
        sl = int(now // 300) * 300 - 300
        bn = {s: m.get(sl) for s, m in bask.items() if s != "ETH" and m.get(sl)}
        bt = {s: m.get(sl - 3600) for s, m in bask.items() if s != "ETH" and m.get(sl - 3600)}
        if bask.get("ETH", {}).get(sl) and bask["ETH"].get(sl - 3600):
            bn["ETH"], bt["ETH"] = bask["ETH"][sl], bask["ETH"][sl - 3600]
        f = bf.compute(now, c1=[], c5=dicts(c5, j5 - 60, j5), c15=dicts(c15, j15 - 100, j15), daily=dd, week=snap["week"], month=snap["month"],
                       oi_hist=oi_hist, funding_pct=fu, ls_ratio=ls, basket_now=bn, basket_then=bt, eth_c15=dicts(e15, je - 8, je))
        if not f.get("ok"):
            continue
        ev = mb.evidence(f)
        mem, tr = mb.step(mem, f, now)
        if tr:
            trans.append((i, tr["to"]["state"], tr["to"]["side"]))
        sg = sigma(i)
        if not sg:
            continue
        row = {"i": i, "day": day, "S": {e["key"] for e in ev["SHORT"]}, "L": {e["key"] for e in ev["LONG"]}, "state": (mem["state"], mem["side"]), "lab": {}}
        px = close1[i]
        row["lead"] = {}
        for h in HORIZONS:
            hs = high1[i + 1:i + 1 + h] / px - 1.0
            ls_ = 1.0 - low1[i + 1:i + 1 + h] / px
            hi, lo = hs.max(), ls_.max()
            thr = K * sg * math.sqrt(h)
            lab = ("up" if hi >= thr and hi > lo else "down" if lo >= thr and lo > hi else None)
            row["lab"][h] = lab
            if lab:   # скільки хвилин від моменту ознаки до першого проходу порога
                arr = hs if lab == "up" else ls_
                row["lead"][h] = int(np.argmax(arr >= thr)) + 1
        samples.append(row)
        n_iter += 1
    print(f"[study] зразків {len(samples)}, переходів стану {len(trans)}, {time.time() - t0:.0f} с", flush=True)
    report(samples, trans, btc1)


def stats(rows, pred, h):
    base_dn = sum(1 for r in rows if r["lab"][h] == "down") / max(1, len(rows))
    base_up = sum(1 for r in rows if r["lab"][h] == "up") / max(1, len(rows))
    sel = [r for r in rows if pred(r)]
    n = len(sel)
    if n == 0:
        return None
    dn = sum(1 for r in sel if r["lab"][h] == "down") / n
    up = sum(1 for r in sel if r["lab"][h] == "up") / n
    leads_dn = [r["lead"][h] for r in sel if r["lab"][h] == "down" and h in r["lead"]]
    leads_up = [r["lead"][h] for r in sel if r["lab"][h] == "up" and h in r["lead"]]
    return {"n": n, "p_down": dn, "p_up": up, "base_down": base_dn, "base_up": base_up, "lift_down": dn / base_dn if base_dn else None, "lift_up": up / base_up if base_up else None,
            "lead_down": (sum(leads_dn) / len(leads_dn)) if leads_dn else None, "lead_up": (sum(leads_up) / len(leads_up)) if leads_up else None}


def boot_ci(rows, pred, h, which, B_=300, seed=7):
    """95% інтервал lift блоками по днях."""
    rng = np.random.default_rng(seed)
    byday = {}
    for r in rows:
        byday.setdefault(r["day"], []).append(r)
    days = list(byday)
    out = []
    for _ in range(B_):
        samp = [byday[d] for d in rng.choice(days, len(days))]
        flat = [r for g in samp for r in g]
        s = stats(flat, pred, h)
        if s and s["lift_" + which]:
            out.append(s["lift_" + which])
    return (round(float(np.percentile(out, 2.5)), 2), round(float(np.percentile(out, 97.5)), 2)) if len(out) > 30 else None


def fmt(s, which):
    if not s:
        return "—"
    p = s["p_" + which]
    b = s["base_" + which]
    l_ = s["lift_" + which]
    wrong = s["p_up" if which == "down" else "p_down"]
    lead = s.get("lead_" + which)
    return (f"n={s['n']:>5} вірно {p * 100:4.1f}% (база {b * 100:4.1f}%) lift={l_:.2f} хибно {wrong * 100:4.1f}% без руху {(1 - p - wrong) * 100:4.1f}% випередж.≈{lead:.0f}хв" if (l_ and lead) else f"n={s['n']}")


def report(samples, trans, btc1):
    cut = int(len(samples) * 0.67)
    train, test = samples[:cut], samples[cut:]
    print(f"\n=== РОЗДІЛЕННЯ: навчальна {len(train)} зразків, перевірочна {len(test)} (за часом, без перемішування) ===")
    conds = []
    for side, sym in (("SHORT", "S"), ("LONG", "L")):
        opp = "L" if sym == "S" else "S"
        for key in ("sweep", "crowd", "level", "breadth", "eth"):
            conds.append((f"{side}: доказ «{key}»", (lambda r, sym=sym, key=key: key in r[sym]), side))
        for nmin in (1, 2, 3):
            conds.append((f"{side}: ≥{nmin} доказів", (lambda r, sym=sym, nmin=nmin: len(r[sym]) >= nmin), side))
        conds.append((f"{side}: ≥2 доказів і відрив ≥2", (lambda r, sym=sym, opp=opp: len(r[sym]) >= 2 and len(r[sym]) - len(r[opp]) >= 2), side))
        for st in ("ACCUM", "SHIFT", "CONFIRMED", "LATE"):
            conds.append((f"{side}: стан {st}", (lambda r, st=st, side=side: r["state"] == (st, side)), side))
    for h in HORIZONS:
        print(f"\n--- ГОРИЗОНТ {h} хв: сильний рух у бік ознаки (down для SHORT, up для LONG) ---")
        for name_, pred, side in conds:
            which = "down" if side == "SHORT" else "up"
            a, b, c = stats(train, pred, h), stats(test, pred, h), stats(samples, pred, h)
            ci = boot_ci(samples, pred, h, which) if c and c["n"] >= 30 else None
            print(f"{name_:<34} НАВЧ {fmt(a, which)} | ПЕРЕВІР {fmt(b, which)} | уся вибірка CI95 lift {ci}")
    print("\n=== ПЕРЕХОДИ СТАНУ (скільки було, і що було потім за 60 хв) ===")
    for st in ("ACCUM", "SHIFT", "CONFIRMED", "LATE", "REVERSAL", "WEAKENING"):
        for side in ("SHORT", "LONG"):
            idxs = [i for i, s_, sd in trans if s_ == st and sd == side]
            if not idxs:
                continue
            row = []
            for h in (30, 60):
                dn = up = 0
                for i in idxs:
                    px = btc1[i, 4]
                    sg = np.std(np.diff(btc1[max(0, i - 1440):i, 4]) / btc1[max(0, i - 1440):i - 1, 4]) if i > 1500 else None
                    if not sg or i + h >= len(btc1):
                        continue
                    thr = K * sg * math.sqrt(h)
                    hi = btc1[i + 1:i + 1 + h, 2].max() / px - 1
                    lo = 1 - btc1[i + 1:i + 1 + h, 3].min() / px
                    dn += lo >= thr and lo > hi
                    up += hi >= thr and hi > lo
                row.append(f"{h} хв: вниз {dn}, вгору {up}")
            print(f"{st:<10}{side:<6} переходів {len(idxs):>4} | " + " | ".join(row))
    print("\nМітка: сильний рух = прохід ≥ 2σ·√h в один бік (σ — 1m за попередні 24 год). База — частота такого руху у всіх зразках.")


if __name__ == "__main__":
    main()
