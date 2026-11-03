"""Завантажує Binance Futures bookDepth (data.binance.vision) і лишає знімок раз на годину. Використання: fetch_bookdepth.py OUT_DIR SYMS from to (YYYY-MM-DD)"""
import sys, io, zipfile, urllib.request, urllib.error, time
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
out, syms, d0, d1 = sys.argv[1], sys.argv[2].split(","), date.fromisoformat(sys.argv[3]), date.fromisoformat(sys.argv[4])
import os; os.makedirs(out, exist_ok=True)

def one(args):
    s, d = args
    url = f"https://data.binance.vision/data/futures/um/daily/bookDepth/{s}/{s}-bookDepth-{d}.zip"
    for att in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r: raw = r.read()
            df = pd.read_csv(zipfile.ZipFile(io.BytesIO(raw)).open(zipfile.ZipFile(io.BytesIO(raw)).namelist()[0]))
            df["ts"] = pd.to_datetime(df["timestamp"]); df["h"] = df.ts.dt.floor("h")
            g = df.sort_values("ts").groupby(["h", "percentage"]).first().reset_index()
            p = g.pivot(index="h", columns="percentage", values="notional"); p.columns = [f"n{int(c)}" for c in p.columns]
            p["ts"] = p.index.astype("int64") // 10**9; return s, p.reset_index(drop=True)
        except urllib.error.HTTPError as e:
            if e.code == 404: return s, None
            time.sleep(2 ** att)
        except Exception: time.sleep(2 ** att)
    return s, None

days = [d0 + timedelta(i) for i in range((d1 - d0).days + 1)]
jobs = [(s, d) for s in syms for d in days]
res = {s: [] for s in syms}
with ThreadPoolExecutor(24) as ex:
    for s, p in ex.map(one, jobs):
        if p is not None: res[s].append(p)
for s, parts in res.items():
    if parts:
        df = pd.concat(parts).sort_values("ts").drop_duplicates("ts"); df.to_csv(f"{out}/{s}.csv", index=False)
        print(s, len(df), "годин; від", pd.to_datetime(df.ts.min(), unit="s"), "до", pd.to_datetime(df.ts.max(), unit="s"))
    else: print(s, "НЕМАЄ ДАНИХ")
