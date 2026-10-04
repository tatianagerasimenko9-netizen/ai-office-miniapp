#!/usr/bin/env python3
"""Linear Regression Channel: еталон Pine (LonesomeTheBlue, v4) vs office_regression_channel.

Еталон тут — НЕЗАЛЕЖНА реалізація семантики Pine (numpy-регресія, а не код Office), побарно: slope, intercept, endy, dev, межі, outofchannel,
стрілка нахилу, trendisup/trendisdown, збереження «пробитої» лінії. Порівнюється з Office; те, чого в Office немає, позначається MISSING.
Використання: python3 scripts/lrc_parity.py            — синтетичні послідовності A–L
              python3 scripts/lrc_parity.py --real      — реальні Binance Futures 15m (data.binance.vision), потрібна мережа (CI)"""
import io
import math
import sys
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_regression_channel as oc  # noqa: E402


# ---------------------------------------------------------------- еталон Pine
def pine_channel(window, devlen=2.0):
    """window — останні len закриттів, від найстарішого до найновішого (src[len-1] … src[0] у термінах Pine)."""
    n = len(window)
    xs = np.arange(n, dtype=float)
    b, a = np.polyfit(xs, np.array(window, dtype=float), 1)   # МНК: y = a + b·x, x=0 — найстаріший бар
    linreg0 = a + b * (n - 1)          # linreg(src, len, 0)
    linreg1 = a + b * (n - 2)          # linreg(src, len, 1)
    slope = linreg0 - linreg1
    mid = float(np.mean(window))
    intercept = mid - slope * math.floor(n / 2) + ((1 - (n % 2)) / 2.0) * slope
    endy = intercept + slope * (n - 1)
    acc = 0.0
    for x in range(n):                 # Pine: src[x] - (slope*(len-x) + intercept), src[0] — останній бар
        acc += (window[n - 1 - x] - (slope * (n - x) + intercept)) ** 2
    dev = math.sqrt(acc / n)
    return {"slope": slope, "intercept": intercept, "endy": endy, "dev": dev,
            "upper_end": endy + dev * devlen, "lower_end": endy - dev * devlen, "upper_start": intercept + dev * devlen, "lower_start": intercept - dev * devlen}


def _sign(v):
    return int(v > 0) - int(v < 0)


def pine_series(closes, length=100, devlen=2.0):
    """Побарно: для кожного бару з достатньою історією — канал + події Pine."""
    out, prev = [], None
    prev_out = None   # outofchannel[1]
    for i in range(length - 1, len(closes)):
        ch = pine_channel(closes[i - length + 1: i + 1], devlen)
        slope, close = ch["slope"], closes[i]
        ooc = 0 if (slope > 0 and close < ch["endy"] - ch["dev"] * devlen) else (2 if (slope < 0 and close > ch["endy"] + ch["dev"] * devlen) else -1)
        ps = prev["slope"] if prev else None
        if slope > 0:
            arrow = "⇑" if (ps is not None and slope > ps) else "⇗"
        elif slope < 0:
            arrow = "⇓" if (ps is not None and slope < ps) else "⇘"
        else:
            arrow = "⇒"
        trend_up = ps is not None and _sign(slope) != _sign(ps) and slope > 0
        trend_dn = ps is not None and _sign(slope) != _sign(ps) and slope < 0
        # showbroken: попередній бар (prev) лінія x == ooc лишається синім пунктиром, якщо ooc ≥ 0 і ooc[1] == -1 (nz(.., -1))
        kept = None
        if ooc >= 0 and (prev_out if prev_out is not None else -1) == -1 and prev:
            kept = {"line_index": ooc, "which": "нижня" if ooc == 0 else "верхня", "geometry_of_bar": i - 1,
                    "y_end": prev["endy"] + prev["dev"] * devlen * (ooc - 1), "y_start": prev["intercept"] + prev["dev"] * devlen * (ooc - 1)}
        out.append({"i": i, **ch, "ooc": ooc, "arrow": arrow, "trend_up": trend_up, "trend_dn": trend_dn,
                    "alert_channel_broken_as_pine_casts": bool(ooc),   # неявне приведення int→bool у Pine v4: 0 → false, будь-яке інше (і -1, і 2) → true
                    "kept_broken": kept})
        prev, prev_out = ch, ooc
    return out


# ---------------------------------------------------------------- Office
def office_channel(window, devlen=2.0):
    rows = [{"close": c} for c in window]
    g = oc.get_channel(window, len(window))
    ch = oc.regression_channel(rows + [{"close": window[-1]}], length=len(window), deviation=devlen, closed_only=True)   # +1 «формується» → відкидається
    intercept, endy, dev, slope = g
    return {"slope": slope, "intercept": intercept, "endy": endy, "dev": dev, "upper_end": ch["upper_end"], "lower_end": ch["lower_end"],
            "upper_start": ch["upper_start"], "lower_start": ch["lower_start"]}


# ---------------------------------------------------------------- синтетичні послідовності
def seq(kind, n=300):
    rng = np.random.default_rng(7)
    t = np.arange(n, dtype=float)
    noise = rng.normal(0, 0.15, n)
    if kind == "A_rising":
        return list(100 + 0.1 * t + noise)
    if kind == "B_falling":
        return list(200 - 0.1 * t + noise)
    if kind == "C_flat":
        return list(100 + noise)
    if kind == "D_rise_flatten":
        return list(100 + np.where(t < 150, 0.12 * t, 0.12 * 150 + 0.0 * (t - 150)) + noise)
    if kind == "E_fall_flatten":
        return list(200 - np.where(t < 150, 0.12 * t, 0.12 * 150) + noise)
    if kind == "F_neg_to_pos":
        return list(150 - np.where(t < 150, 0.1 * t, 0.1 * 150 - 0.12 * (t - 150)) + noise)
    if kind == "G_pos_to_neg":
        return list(100 + np.where(t < 150, 0.1 * t, 0.1 * 150 - 0.12 * (t - 150)) + noise)
    if kind == "H_up_channel_down_break":
        return list(100 + 0.1 * t - np.where(t > 250, 0.9 * (t - 250), 0) + noise)
    if kind == "I_down_channel_up_break":
        return list(200 - 0.1 * t + np.where(t > 250, 0.9 * (t - 250), 0) + noise)
    if kind == "J_move_in_direction":
        return list(100 + 0.1 * t + np.where(t > 250, 0.9 * (t - 250), 0) + noise)
    if kind == "K_high_vol":
        return list(100 + 0.05 * t + rng.normal(0, 2.0, n))
    if kind == "L_low_vol":
        return list(100 + 0.05 * t + rng.normal(0, 0.01, n))
    raise KeyError(kind)


KINDS = ["A_rising", "B_falling", "C_flat", "D_rise_flatten", "E_fall_flatten", "F_neg_to_pos", "G_pos_to_neg", "H_up_channel_down_break", "I_down_channel_up_break",
         "J_move_in_direction", "K_high_vol", "L_low_vol"]
FIELDS = ("slope", "intercept", "endy", "dev", "upper_end", "lower_end", "upper_start", "lower_start")


def compare_window(window, devlen=2.0):
    p, o = pine_channel(window, devlen), office_channel(window, devlen)
    return {k: abs(p[k] - o[k]) / max(1.0, abs(p[k])) for k in FIELDS}


# ---------------------------------------------------------------- реальні дані
def fetch_closes(symbol, interval, day):
    url = f"https://data.binance.vision/data/futures/um/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{day}.zip"
    with urllib.request.urlopen(url, timeout=40) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    rows = []
    for name in z.namelist():
        for line in io.TextIOWrapper(z.open(name)):
            f = line.strip().split(",")
            try:
                rows.append((int(f[0]), float(f[4])))
            except ValueError:
                continue
    return rows


def real_main():
    day0 = (datetime.now(timezone.utc) - timedelta(days=3)).date()
    days = [(day0 - timedelta(days=k)).isoformat() for k in (5, 4, 3, 2, 1, 0)]
    print(f"{'symbol':8} {'end_ts':20} {'slope(pine)':>14} {'slope(office)':>14} {'max_rel_diff':>13}")
    worst, compared = 0.0, 0
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ONEUSDT", "LTCUSDT"):
        rows = []
        for d in days:
            try:
                rows += fetch_closes(sym, "15m", d)
            except Exception as exc:  # noqa: BLE001
                print(f"{sym} {d}: немає архіву ({type(exc).__name__})")
        rows.sort()
        closes = [c for _t, c in rows]
        if len(closes) < 300:
            continue
        for end in (len(closes) - 1, len(closes) - 50, len(closes) - 120, len(closes) - 200):
            w = closes[end - 99: end + 1]
            p, o = pine_channel(w), office_channel(w)
            d = max(abs(p[k] - o[k]) / max(1.0, abs(p[k])) for k in FIELDS)
            worst = max(worst, d)
            compared += 1
            print(f"{sym:8} {datetime.fromtimestamp(rows[end][0] / 1000, tz=timezone.utc).strftime('%m-%d %H:%M'):20} {p['slope']:14.8g} {o['slope']:14.8g} {d:13.3e}")
    if not compared:
        print("НЕМАЄ ДАНИХ: жодного порівняння не виконано")
        return 2
    print(f"ПОРІВНЯНО ВІКОН: {compared}; МАКС. ВІДНОСНА РІЗНИЦЯ (реальні дані): {worst:.3e}")
    return 0 if worst < 1e-9 else 1


def main():
    if "--real" in sys.argv:
        return real_main()
    worst = 0.0
    print(f"{'послідовність':26} " + " ".join(f"{k:>10}" for k in FIELDS))
    for kind in KINDS:
        closes = seq(kind)
        diffs = {k: 0.0 for k in FIELDS}
        for end in range(99, len(closes), 25):
            for k, v in compare_window(closes[end - 99: end + 1]).items():
                diffs[k] = max(diffs[k], v)
        worst = max(worst, max(diffs.values()))
        print(f"{kind:26} " + " ".join(f"{diffs[k]:10.1e}" for k in FIELDS))
    print("МАКС. ВІДНОСНА РІЗНИЦЯ (синтетика):", f"{worst:.3e}")
    return 0 if worst < 1e-9 else 1


if __name__ == "__main__":
    sys.exit(main())
