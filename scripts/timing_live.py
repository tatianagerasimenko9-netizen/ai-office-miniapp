"""READ-ONLY. Коли живі TD-угоди 3-8 листопада вперше були в плюсі >= X R (за закриттям M15) і чим закінчились. Використання: timing_live.py CANDLES_DIR (запускати з кореня репо)"""
import sys, re
from datetime import datetime, timezone
import numpy as np, pandas as pd
CD = sys.argv[1]
src = open("scripts/postmortem_td.py").read(); a = src.index("T = ["); b = src.index("]\ndef load") + 1
ns = {}; exec(src[a:b], ns); T = ns["T"]
def ts(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()
D = {}
print("| № | монета | напрям | закінчилась | годин відкрита | перший +0,5R | перший +1R | перший +2R | пік R до виходу/кінця даних |\n|--|--|--|--|--|--|--|--|--|")
rows = []
for seq, sym, side, c0, ent, sl, tp, slt in T:
    if sym not in D: D[sym] = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    d = D[sym]; t_in = ts(c0) + 900; end_data = float(d.open_time.max()) + 900
    if t_in >= end_data - 900: print(f"| {seq} | {sym[:-4]} | {'LONG' if side>0 else 'SHORT'} | сьогодні, даних ще немає | | | | | |"); continue
    risk = abs(ent - sl); t_end = ts(slt) if slt else end_data
    seg = d[(d.open_time >= t_in) & (d.open_time < t_end)]
    if len(seg) == 0: continue
    r_close = side * (seg.close.to_numpy() - ent) / risk; hrs = (seg.open_time.to_numpy() + 900 - t_in) / 3600
    r_peak = side * ((seg.high.max() - ent) if side > 0 else (ent - seg.low.min())) / risk
    f = lambda X: (f"{hrs[np.where(r_close >= X)[0][0]]:.1f} год" if (r_close >= X).any() else "ні")
    status = "стоп" if slt and abs(tp - ent) / risk > 0 and not (slt and False) else "відкрита"
    end_s = "ціль" if seq == 21 else ("стоп" if slt else ("час 48 год" if seq == 5 else "відкрита"))
    print(f"| {seq} | {sym[:-4]} | {'LONG' if side>0 else 'SHORT'} | {end_s} | {(t_end - t_in)/3600:.1f} | {f(0.5)} | {f(1.0)} | {f(2.0)} | {r_peak:+.1f}R |")
    rows.append((seq, end_s, hrs, r_close))
print()
for X in (1.0, 2.0):
    got = [(s, e, h[np.where(r >= X)[0][0]]) for s, e, h, r in rows if (r >= X).any()]
    print(f"+{X:g}R досягли {len(got)} із {len(rows)} угод з даними; з них закінчились: " + ", ".join(f"{e}: {sum(1 for _, ee, _ in got if ee == e)}" for e in sorted({e for _, e, _ in got})) + f"; медіана часу до першого +{X:g}R: {np.median([g[2] for g in got]):.1f} год" if got else f"+{X:g}R не досяг ніхто")
print("\n##### ПІДСУМОК timing_live завершено")
