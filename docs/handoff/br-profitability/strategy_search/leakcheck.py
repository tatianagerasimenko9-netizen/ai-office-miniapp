"""Перевірка на підгляд у майбутнє: значення ознак на барі i мають збігатись, якщо відрізати всі бари після i. Використання: leakcheck.py CANDLES_DIR SYM"""
import sys
CD, SYM = sys.argv[1], sys.argv[2]; sys.argv = ['x', CD, SYM + ',BTCUSDT', '0.001']
import numpy as np, pandas as pd
import ml_discover3 as md
d = md.load_h1(SYM); b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
d = d.iloc[:min(len(d), 20000)].reset_index(drop=True)
def full(dd):
    t, o, h, l, c, atr, F, EX = md.feats(dd, btc); return F, EX["E"], EX
F, E, EX = full(d); rng = np.random.default_rng(1); bad = {}; N = 25
for i in rng.integers(2500, len(d) - 10, N):
    Fp, Ep, EXp = full(d.iloc[:i + 1].reset_index(drop=True))
    for k, (v, mode) in E.items():
        a = v[0] if isinstance(v, tuple) else v; ap = Ep[k][0][0] if isinstance(Ep[k][0], tuple) else Ep[k][0]
        if not np.isclose(a[i], ap[i], equal_nan=True, rtol=1e-6, atol=1e-9): bad[k] = bad.get(k, 0) + 1
    for k, v in F.items():
        if not np.isclose(v[i], Fp[k][i], equal_nan=True, rtol=1e-6, atol=1e-9): bad["F:" + k] = bad.get("F:" + k, 0) + 1
    for P, (PH, PL) in EX["LV"].items():
        for nm, A_, B_ in (("PH", PH, EXp["LV"][P][0]), ("PL", PL, EXp["LV"][P][1])):
            if not np.isclose(A_[i], B_[i], equal_nan=True): bad[f"LV:{P}{nm}"] = bad.get(f"LV:{P}{nm}", 0) + 1
print(f"##### LEAKCHECK {SYM}: перевірено {N} випадкових барів; ознаки з підглядом:", bad if bad else "жодної")
