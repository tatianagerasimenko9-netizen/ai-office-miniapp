"""READ-ONLY. Перевірка ЗАФІКСОВАНОГО правила на історії, яку дерево НЕ бачило (інший період).
Правило-кандидат з reverse_search (листок): pos_range24>0.78 (ціна в бік угоди в верхніх 22% діапазону 24 год), compress>0.18,
asia_pos>0.49, [dow Чт-Сб — окремий варіант]. Ціль 3R, стоп = екстремум 8 барів ∓0.1 ATR, горизонт 24 год.
Використання: eval_rule.py CANDLES_DIR SYMS COST"""
import sys, random
import numpy as np, pandas as pd
sys.argv_backup = list(sys.argv)
import reverse_search as rs
DAY = 86400
def main():
    rows = []
    btc = rs.load("BTCUSDT"); btc_ret = {}
    if btc is not None:
        bt = btc.open_time.to_numpy(float); bc = btc.close.to_numpy(float)
        for i in range(4, len(bc)): btc_ret[int(bt[i] // 900)] = np.sign(bc[i] - bc[i - 4])
    for s in rs.SYMS:
        d = rs.load(s)
        if d is None: continue
        r = rs.build(d, btc_ret)
        for x in r: x["sym"] = s
        rows += r
    df = pd.DataFrame(rows).sort_values("t").reset_index(drop=True)
    print(f"Період {pd.to_datetime(df.t.min(), unit='s')} .. {pd.to_datetime(df.t.max(), unit='s')}; входів без фільтра {len(df)}; R без фільтра {df.r.mean():+.3f}; комісія {rs.COST*100:.2f}%")
    base = (df.pos_range24 > 0.78) & (df.compress > 0.18) & (df.asia_pos > 0.49)
    variants = {"A: pos24>0.78 & compress>0.18 & asia_pos>0.49": base,
                "B: A + дні Чт-Сб": base & (df.dow > 3.5),
                "C: лише pos24>0.78 & compress>0.18": (df.pos_range24 > 0.78) & (df.compress > 0.18),
                "D: лише pos24>0.78": df.pos_range24 > 0.78}
    for nm, m in variants.items():
        x = df[m].sort_values(["sym", "side", "t"])
        # дедуплікація: 1 угода на монету+напрям на 2 години (відсікає перекриті входи)
        keep = (x.sym != x.sym.shift()) | (x.side != x.side.shift()) | (x.t - x.t.shift() > 7200)
        # перший у кластері
        grp = keep.cumsum(); y = x.groupby(grp).head(1)
        days = max(1, (df.t.max() - df.t.min()) / DAY)
        by_m = y.groupby(pd.to_datetime(y.t, unit="s").dt.to_period("M")).r.agg(["count", "mean", "sum"])
        pos_m = int((by_m["sum"] > 0).sum())
        dd = {}
        for tt, r in zip(y.t, y.r): dd.setdefault(int(tt // DAY), []).append(r)
        lo, hi = rs.boot(dd)
        print(f"\n{nm}\n  сирих входів {len(x)}, після дедуплікації {len(y)} (≈{len(y)/days:.1f} на добу на 12 монет); R/угоду {y.r.mean():+.3f} CI95 [{lo:+.3f}; {hi:+.3f}]; $ при $10/угоду {10*y.r.sum():+,.0f}; місяців у плюсі {pos_m} з {len(by_m)}")
        for sess, mm in (("Азія", y.sess_asia == 1), ("Лондон", y.sess_london == 1), ("Нью-Йорк", y.sess_ny == 1)):
            z = y[mm]; print(f"    {sess}: n={len(z)}, R={z.r.mean():+.3f}, $={10*z.r.sum():+,.0f}")
        print("    по місяцях (n, R/угоду):", ", ".join(f"{str(k)[2:]}:{int(v['count'])}/{v['mean']:+.2f}" for k, v in by_m.iterrows()))
main()
