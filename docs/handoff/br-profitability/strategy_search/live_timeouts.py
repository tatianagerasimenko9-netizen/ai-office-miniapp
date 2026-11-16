"""READ-ONLY. Що було з 6 живими угодами, які закрилися «за часом 48 год»: результат на 48 год і що було далі (ціль/стоп/ціна на кінець даних). Використання: live_timeouts.py CANDLES_DIR"""
import sys
import pandas as pd
from datetime import datetime, timezone
CD = sys.argv[1]
T = [(5, "XRPUSDT", -1, 1.1897, 1.20787, 1.10977, 1793945760), (19, "ATOMUSDT", -1, 1.387, 1.41071, 1.2456, 1794008751), (44, "BNBUSDT", -1, 683.7, 698.636, 623.669, 1794177952),
     (47, "NATGASUSDT", 1, 3.484, 3.40544, 3.78114, 1794333643), (54, "XAGUSDT", -1, 52.09, 52.456, 48.6915, 1794420013), (58, "BNBUSDT", -1, 651.52, 662.45957, 593.45614, 1794493821)]
f = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%d.%m %H:%M")
tot48 = 0.0
for seq, sym, side, ent, sl, tp, t0 in T:
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time"); d = d[d.open_time >= t0 - 900]
    risk = abs(ent - sl); end48 = t0 + 48 * 3600; ev1 = None; ev2 = None; last = d.iloc[-1]
    for r in d.itertuples():
        if r.open_time < t0: continue
        hit_sl = r.low <= sl if side > 0 else r.high >= sl; hit_tp = r.high >= tp if side > 0 else r.low <= tp
        ev = "SL" if hit_sl else ("TP" if hit_tp else None)
        if ev:
            if r.open_time < end48: ev1 = (ev, r.open_time)
            else: ev2 = ev2 or (ev, r.open_time)
            if ev1 or ev2: break
    at48 = d[d.open_time >= end48 - 900].iloc[0].open if (d.open_time >= end48 - 900).any() else float("nan")
    r48 = side * (at48 - ent) / risk; tot48 += 10 * r48
    aft = d[d.open_time >= end48]
    best = (side * (aft.high.max() - ent) / risk if side > 0 else side * (aft.low.min() - ent) / risk) if len(aft) else float("nan")
    worst = (side * (aft.low.min() - ent) / risk if side > 0 else side * (aft.high.max() - ent) / risk) if len(aft) else float("nan")
    rl = side * (last.close - ent) / risk
    print(f"№{seq} {sym[:-4]} {'LONG' if side>0 else 'SHORT'}: на 48 год {r48:+.2f}R (${10*r48:+.0f}); " + (f"ПІСЛЯ 48 год: {ev2[0]} о {f(ev2[1])}" if ev2 else ("до 48 год вже було " + ev1[0] if ev1 else "ні цілі, ні стопа до кінця даних")) + f"; після 48 год екстремуми {worst:+.2f}R..{best:+.2f}R; на кінець даних ({f(last.open_time)}) {rl:+.2f}R (${10*rl:+.0f})")
print(f"\nСума на момент 48 год по 6 угодах: ${tot48:+.0f}")
