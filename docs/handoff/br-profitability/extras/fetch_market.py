"""Фандінг (місячні архіви) і metrics (денні, 5-хв: OI, лонг/шорт, taker) з data.binance.vision → CSV (t сек, ...). Лише читання."""
import sys, io, zipfile, urllib.request, urllib.error, datetime as dt, csv, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
out, syms = Path(sys.argv[1]), sys.argv[2].split(","); a, b = dt.date.fromisoformat(sys.argv[3]), dt.date.fromisoformat(sys.argv[4])
def get(url):
    for k in range(4):
        try: return urllib.request.urlopen(url, timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(2 * (k + 1))
        except Exception: time.sleep(2 * (k + 1))
    return None
def fund(s):
    rows = []; m = dt.date(a.year, a.month, 1)
    while m <= b:
        raw = get(f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m:%Y-%m}.zip")
        if raw:
            z = zipfile.ZipFile(io.BytesIO(raw))
            for ln in z.read(z.namelist()[0]).decode().splitlines():
                p = ln.split(",")
                if p[0].isdigit(): rows.append((int(p[0]) // 1000, float(p[2])))
        m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return s, sorted(rows)
def met_day(j):
    s, d = j; raw = get(f"https://data.binance.vision/data/futures/um/daily/metrics/{s}/{s}-metrics-{d}.zip"); rows = []
    if raw:
        z = zipfile.ZipFile(io.BytesIO(raw))
        for ln in z.read(z.namelist()[0]).decode().splitlines()[1:]:
            p = ln.split(",")
            try:
                t = int(dt.datetime.strptime(p[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp())
                if t % (4 * 3600) == 0: rows.append((t, float(p[3] or 0), float(p[6] or 0), float(p[7] or 0)))   # OI value, count L/S ratio, taker vol ratio
            except Exception: pass
    return s, rows
(out / "funding").mkdir(parents=True, exist_ok=True); (out / "metrics").mkdir(parents=True, exist_ok=True)
with ThreadPoolExecutor(12) as ex:
    for s, rows in ex.map(fund, syms):
        with open(out / "funding" / f"{s}.csv", "w", newline="") as f: w = csv.writer(f); w.writerow(["t", "v"]); w.writerows(rows)
    jobs = []; d = a
    while d <= b: jobs += [(s, d) for s in syms]; d += dt.timedelta(days=1)
    acc = {}
    for s, rows in ex.map(met_day, jobs): acc.setdefault(s, []).extend(rows)
for s, rows in acc.items():
    with open(out / "metrics" / f"{s}.csv", "w", newline="") as f: w = csv.writer(f); w.writerow(["t", "oi", "ls", "taker"]); w.writerows(sorted(rows))
print({s: len(r) for s, r in acc.items()})
