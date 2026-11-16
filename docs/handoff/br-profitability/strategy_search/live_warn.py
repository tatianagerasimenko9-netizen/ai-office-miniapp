"""READ-ONLY. Перевірка ЖИВОГО коду попередження (office_td/warn.py) на вже надісланих сигналах №1-86: на яких спрацювало б, причини, що було з угодами. Використання: live_warn.py CANDLES_DIR SIGNALS_CSV REPO_ROOT"""
import sys, numpy as np, pandas as pd
from datetime import datetime, timezone
CD, SIG, ROOT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, ROOT)
from office_td import warn as W
def h1(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // 3600 * 3600).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    return [dict(ts=datetime.fromtimestamp(r.open_time, timezone.utc).isoformat(), open=r.open, high=r.high, low=r.low, close=r.close, volume=1.0) for r in g.itertuples()]
S = pd.read_csv(SIG); S["sym"] = S.sym.where(S.sym.str.endswith("USDT"), S.sym + "USDT"); H = {}; rows = []
for r in S.itertuples():
    try:
        if r.sym not in H: H[r.sym] = h1(r.sym)
        if "BTCUSDT" not in H: H["BTCUSDT"] = h1("BTCUSDT")
        ent = r.entry; t0 = float(r.t0); cut = t0 // 3600 * 3600
        hh = [x for x in H[r.sym] if datetime.fromisoformat(x["ts"]).timestamp() < cut + 3600]   # дані до моменту картки (останній бар може бути поточної години → відсікається в compute)
        if len(hh) < 200 or datetime.fromisoformat(hh[-1]["ts"]).timestamp() < cut - 3600: rows.append(None); continue
        R = abs(r.tp - ent) / abs(ent - r.sl); usd = {"SL": -10.0, "TP1": 10 * R}.get(r.status)
        w = W.compute(1 if r.side > 0 else -1, ent, r.sl, hh, H["BTCUSDT"], t0)
        rows.append(dict(seq=r.seq, sym=r.sym[:-4], side="L" if r.side > 0 else "S", status=r.status, usd=usd, warn=" | ".join(w), flag=bool(w)))
    except Exception as e:
        print("помилка", r.seq, type(e).__name__, e); rows.append(None)
D = pd.DataFrame([x for x in rows if x]); print(f"Сигналів з даними: {len(D)} із {len(S)}")
print(D[D.flag].to_string(index=False))
def tot(x): return f"{x.usd.dropna().sum():+.0f}$ (закритих {x.usd.notna().sum()}, виграшних {(x.usd.dropna() > 0).sum()}, стопів {(x.usd.dropna() < 0).sum()})"
print(f"\nЗ попередженням: {D.flag.sum()} ({D.flag.mean()*100:.0f}%): {tot(D[D.flag])}; статуси {D[D.flag].status.value_counts().to_dict()}")
print(f"Без попередження: {(~D.flag).sum()}: {tot(D[~D.flag])}; статуси {D[~D.flag].status.value_counts().to_dict()}")
print(f"Усі: {tot(D)}")
