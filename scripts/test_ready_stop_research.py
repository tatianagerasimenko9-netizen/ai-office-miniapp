#!/usr/bin/env python3
"""Самоперевірка дослідження стопів на синтетичних 1m-свічках (без мережі): порядок SL/TP1, R при незмінному ризику, фрактали, lookahead, NO_DATA, наскрізний прогін."""
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
import ready_stop_research as sr  # noqa: E402

FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)
        print("FAIL:", msg)


T0 = 1_790_000_000 - (1_790_000_000 % 86400)   # початок доби UTC
H24 = 24 * 3600


def rows_from(path, start=T0):
    return [[start + 60 * i, c, h, l, c, 1.0] for i, (h, l, c) in enumerate(path)]


flat = (100.5, 99.5, 100.0)


def mk(path):
    r = rows_from(path)
    return r, [x[0] for x in r]


# Дані на 2 доби, щоб вистачило горизонту 24 год
def series(events):
    p = [flat] * (2 * 1440)
    for i, v in events.items():
        p[i] = v
    return p


ct = T0 + 600 * 60
i_ct = 600
# a) TP1 першим
r, t = mk(series({i_ct + 5: (105.0, 100.0, 104.5)}))
res = sr.walk(r, t, ct, ct + 86400, 100.0, 98.0, 104.0, True)
check(res["status"] == "TP1", f"TP1 першим: {res['status']}")
check(abs(sr.r_multiple(res, 100.0, 98.0, 104.0, True) - (4 / 2 - 0.001 * 100 / 2)) < 1e-9, "R для TP1 = відстань до цілі / відстань до стопу − комісія/стоп")
# б) SL першим
r, t = mk(series({i_ct + 5: (100.0, 97.0, 97.5)}))
res = sr.walk(r, t, ct, ct + 86400, 100.0, 98.0, 104.0, True)
check(res["status"] == "SL" and abs(sr.r_multiple(res, 100.0, 98.0, 104.0, True) - (-1 - 0.001 * 100 / 2)) < 1e-9, f"SL = −1R − комісія: {res['status']}")
# в) одна хвилина і стоп, і ціль → SL
r, t = mk(series({i_ct + 5: (105.0, 97.0, 100.0)}))
check(sr.walk(r, t, ct, ct + 86400, 100.0, 98.0, 104.0, True)["status"] == "SL", "стоп і ціль в одній хвилині = SL")
# г) lookahead: до ct екстремум не враховується
r, t = mk(series({i_ct - 10: (100.0, 90.0, 95.0)}))
check(sr.walk(r, t, ct, ct + 86400, 100.0, 98.0, 104.0, True)["status"] == "NONE", "рух до READY ігнорується")
# д) NO_DATA, якщо дані не покривають горизонт
r, t = mk([flat] * 700)
check(sr.walk(r, t, ct, ct + 86400, 100.0, 98.0, 104.0, True)["status"] == "NO_DATA", "немає даних до горизонту = NO_DATA")
# е) ширший стоп при тому ж ризику $: TP1 дає менше R, SL так само −1R
res = {"status": "TP1"}
r_tight = sr.r_multiple(res, 100.0, 99.0, 104.0, True)
r_wide = sr.r_multiple(res, 100.0, 98.0, 104.0, True)
check(r_wide < r_tight, "ширший стоп → менше R на TP1 при тому ж ризику $")
check(abs(sr.r_multiple({"status": "SL"}, 100.0, 98.0, 104.0, True) - sr.r_multiple({"status": "SL"}, 100.0, 99.0, 104.0, True)) <= 0.0501, "SL ≈ −1R незалежно від ширини (комісія в R менша для ширшого)")
# ж) фрактали
bars = [(i * 900.0, 100, 100 + (5 if i == 10 else 1), 99 - (4 if i == 20 else 0), 100) for i in range(40)]
fr = sr.fractals(bars)
check(any(t == "H" and i == 10 for i, t, _ in fr) and any(t == "L" and i == 20 for i, t, _ in fr), f"фрактали знайдено: {fr}")
check(not any(i >= 38 for i, _t, _p in fr), "останні K барів не бувають фракталами")
v = sr.stop_variants(100.0, 98.0, True, 1.0, [(20, "L", 96.0), (5, "L", 99.0)])   # найближчий фрактал нижче входу = 99
check(abs(v["фрактал15m+0.5ATR"] - 98.5) < 1e-9 and v["2×ATR15"] == 98.0 and v["поточний×1.5"] == 97.0, f"варіанти стопу: {v}")
vs = sr.stop_variants(100.0, 102.0, False, 1.0, [(7, "H", 104.0)])
check(abs(vs["фрактал15m+0.25ATR"] - 104.25) < 1e-9, f"SHORT: стоп над найближчим фракталом: {vs}")
# з) блоковий бутстреп
m, lo, hi = sr.block_ci([(1, 1.0), (1, 1.0), (2, -1.0), (3, 0.0)])
check(lo <= m <= hi, "бутстреп: середнє в інтервалі")

# к) рівні ліквідності: H1-фрактал і PDH/PDL; без lookahead
base_t = T0 - 2 * 86400
lv_rows = []
for k in range(4 * 1440):
    t_ = base_t + 60 * k
    hh = (t_ - base_t) / 3600.0
    hi_ = 100.5 + (6.0 if 30 <= hh < 31 else 0.0) + (9.0 if 80 <= hh < 81 else 0.0)   # пік у годині 30 (до ct) і в годині 80 (після ct)
    lv_rows.append([t_, 100.0, hi_, 99.5, 100.0, 1.0])
lv_times = [x[0] for x in lv_rows]
ct_lv = base_t + 60 * 3600   # година 60
levels = sr.h1_levels(lv_rows, lv_times, ct_lv)
check(any(n == "H1-high" and abs(p - 106.5) < 1e-9 for n, p in levels), f"H1-фрактал піку до ct знайдено: {levels[:4]}")
check(not any(abs(p - 109.5) < 1e-9 for _n, p in levels), "пік ПІСЛЯ ct не потрапляє в рівні (без lookahead)")
check(any(n == "PDH" for n, _p in levels) and any(n == "PDL" for n, _p in levels), "є PDH/PDL")
# і) наскрізний офлайн-прогін на синтетичних архівах
tmp = Path(tempfile.mkdtemp())
cache = tmp / "cache"
cache.mkdir()
day0 = datetime.fromtimestamp(T0, tz=timezone.utc)
plans = []
import random
random.seed(3)
for sym in ("TESTUSDT", "BTCUSDT"):
    for dd in range(-1, 4):
        d = day0 + timedelta(days=dd)
        st = d.timestamp()
        rows = []
        px = 100.0
        for k in range(1440):
            px *= 1 + random.gauss(0, 0.0007)
            rows.append([st + 60 * k, px, px * 1.0006, px * 0.9994, px, 1.0])
        (cache / f"{sym}-1m-{d:%Y-%m-%d}.json").write_text(json.dumps(rows))
for k in range(40):
    c = T0 + 3600 * (3 + k % 10) + 60 * k
    ent = 100.0
    plans.append({"mid": str(k), "symbol": "TESTUSDT", "direction": "LONG" if k % 2 == 0 else "SHORT", "tf": "H1", "ct": str(c), "vt": str(c + 86400), "entry": "100", "sl": "98.5" if k % 2 == 0 else "101.5", "tp1": "104" if k % 2 == 0 else "96", "regime": "RANGE"})
pj = tmp / "plans.json"
pj.write_text(json.dumps(plans))
out = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "ready_stop_research.py"), "--plans", str(pj), "--cache", str(cache), "--offline"], capture_output=True, text=True)
check(out.returncode == 0, f"наскрізний прогін повернув 0: rc={out.returncode} err={out.stderr[-400:]}")
check("## 1." in out.stdout and "## 2." in out.stdout and "## 3." in out.stdout, "звіт містить розділи 1–3")
check("N=0" not in out.stdout.split("\n")[2] if len(out.stdout.split("\n")) > 2 else False, "порівняння відбулись (N>0): інакше це «0 порівнянь», а не PASS")
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)
