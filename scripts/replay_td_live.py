"""READ-ONLY діагностика: що знайшов би живий скан TD-V1 (office_td.live.score_symbol) на реальних свічках за останні дні. Порівняння з тим, що записав живий сервіс.
Використання: replay_td_live.py CANDLES_DIR FROM_ISO TO_ISO"""
import sys, json
from datetime import datetime, timezone
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from office_td import live as L

CD, T0, T1 = sys.argv[1], sys.argv[2], sys.argv[3]
m = L.model(); thr = m.threshold
def load(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // 3600 * 3600).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).reset_index()
    return g
H = {s: load(s) for s in L.SYMBOLS}
def bars(sym, upto):                               # лише закриті H1-бари: open_time < upto (upto — момент закриття)
    g = H[sym]; g = g[g.open_time + 3600 <= upto].tail(L.H1_BARS)
    return [dict(ts=datetime.fromtimestamp(float(r.open_time), timezone.utc).isoformat(), open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume) for r in g.itertuples()]
t0 = datetime.fromisoformat(T0).replace(tzinfo=timezone.utc).timestamp(); t1 = datetime.fromisoformat(T1).replace(tzinfo=timezone.utc).timestamp()
last = {}; found = []; per_day = {}
for hh in np.arange(t0, t1 + 1, 3600):
    btc = bars("BTCUSDT", hh)
    if len(btc) < L.MIN_H1: continue
    for sym in L.SYMBOLS:
        b = btc if sym == "BTCUSDT" else bars(sym, hh)
        if len(b) < L.MIN_H1: continue
        for r in L.score_symbol(sym, b, btc, m):
            if r["score"] < thr: continue
            k = (sym, r["direction"])
            if k in last and r["h1_ts"] - last[k] < L.DEDUPE_S: continue
            last[k] = r["h1_ts"]; day = datetime.fromtimestamp(r["h1_ts"], timezone.utc).strftime("%Y-%m-%d")
            per_day[day] = per_day.get(day, 0) + 1
            found.append((datetime.fromtimestamp(r["h1_ts"], timezone.utc).strftime("%Y-%m-%d %H:%M"), sym, r["direction"], round(r["score"], 3)))
print(f"Поріг {thr:.4f}; період {T0} .. {T1} (UTC), монети {len(L.SYMBOLS)}")
print("Кандидатів за добами (як у живому скані, дедуплікація 12 год):", per_day)
print(f"Усього {len(found)}; у середньому {len(found)/max(1,len(per_day)):.1f} на добу")
for f in found: print("  ", *f)
print("\n(Порівняння з БД — окремо)")
print("##### ПІДСУМОК replay_td_live завершено")
