"""Read-only: тягне свічки Binance USDT-M Futures з data.binance.vision у candles/{SYM}/{tf}.csv (open_time у СЕКУНДАХ, open,high,low,close).
Використання: fetch_binance_klines.py OUT_DIR SYMBOLS(comma) 1m:2026-10-15:2026-11-01 1h:2026-09-15:2026-11-01 ...  (tf:from:to, денні архіви)"""
import csv, io, sys, zipfile, urllib.request, urllib.error, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
out, syms = Path(sys.argv[1]), sys.argv[2].split(",")
jobs = []
for spec in sys.argv[3:]:
    tf, a, b = spec.split(":"); d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    for s in syms:
        d = d0
        while d <= d1: jobs.append((s, tf, d)); d += dt.timedelta(days=1)
def get(j):
    s, tf, d = j
    url = f"https://data.binance.vision/data/futures/um/daily/klines/{s}/{tf}/{s}-{tf}-{d}.zip"
    try:
        raw = urllib.request.urlopen(url, timeout=60).read()
    except urllib.error.HTTPError:
        return j, []
    rows = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for ln in z.read(z.namelist()[0]).decode().splitlines():
            p = ln.split(",")
            if not p[0].isdigit(): continue
            t = int(p[0]); t = t // 1000 if t > 10**11 else t
            rows.append((t, p[1], p[2], p[3], p[4]))
    return j, rows
data = {}
with ThreadPoolExecutor(16) as ex:
    for (s, tf, d), rows in ex.map(get, jobs): data.setdefault((s, tf), []).extend(rows)
for (s, tf), rows in data.items():
    rows.sort(); p = out / s; p.mkdir(parents=True, exist_ok=True)
    with open(p / f"{tf}.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["open_time", "open", "high", "low", "close"]); w.writerows(rows)
    print(s, tf, len(rows))
