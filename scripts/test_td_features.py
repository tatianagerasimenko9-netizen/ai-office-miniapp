"""Еквівалентність ознак office_td.features ↔ ml_discover2 (на яких навчалась модель). Пропускається без sklearn."""
import sys, os, tempfile
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import sklearn  # noqa: F401
except Exception:
    print("SKIP: немає sklearn"); sys.exit(0)
SD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "handoff", "br-profitability", "strategy_search")
sys.path.insert(0, SD)
sys.argv = ["x", tempfile.gettempdir(), "X", "0.001"]
import ml_discover2 as md
from office_td import features as tf

rng = np.random.default_rng(5); n = 4200
t = 1700000000 // 3600 * 3600 + np.arange(n) * 3600.0
def series(seed, vol):
    r = np.random.default_rng(seed); p = 100 * np.exp(np.cumsum(r.normal(0, vol, n)))
    o = np.r_[p[0], p[:-1]]; h = np.maximum(o, p) * (1 + abs(r.normal(0, 0.002, n))); l = np.minimum(o, p) * (1 - abs(r.normal(0, 0.002, n)))
    return o, h, l, p, r.uniform(50, 500, n)
o, h, l, c, v = series(1, 0.006); bo, bh, bl, bc, bv = series(2, 0.004)
d = pd.DataFrame(dict(open_time=t, open=o, high=h, low=l, close=c, volume=v))
btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=t)
ref = md.rows_for("X", d, btc)
B = tf.compute(t, o, h, l, c, v, btc["r4"].to_numpy(), btc["r24"].to_numpy())
bad = 0; checked = 0
for s in (1, -1):
    r = ref[ref.side == s].reset_index(drop=True)
    ii = np.searchsorted(t, r.t.to_numpy())
    f, ent, sl, sp = tf.side_features(B, ii, s)
    for k, arr in f.items():
        if k not in r.columns: print("ЗАЙВА ознака", k); bad += 1; continue
        if not np.allclose(arr, r[k].to_numpy(), equal_nan=True, rtol=1e-9, atol=1e-12): print("РОЗБІЖНІСТЬ", k, s); bad += 1
        checked += 1
    missing = [k for k in r.columns if k not in f and k not in ("t", "r", "side", "sym", "ent", "sl")]
    if missing: print("НЕ ВИСТАЧАЄ ознак:", missing); bad += 1
    if not (np.allclose(ent, r.ent) and np.allclose(sl, r.sl)): print("ent/sl розбіжність", s); bad += 1
print(f"перевірено {checked} стовпців, рядків {len(ref)}; розбіжностей {bad}")
assert bad == 0
print("OK test_td_features")
