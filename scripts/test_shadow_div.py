"""Тихий журнал дивергенцій (офлайн): сигнал на останньому барі збігається з еталонним проходом (як у div_lab.py), геометрія стоп 2×ATR / ціль 6R, запис без повідомлень, один відкритий на монету і вид, закриття, вимикач."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from office_td import shadow_div as sd
from office_bridge import _fetchall
rng = np.random.default_rng(11); N = 900
c = 100 * np.exp(np.cumsum(rng.normal(-0.0003, 0.012, N))); o = np.r_[c[0], c[:-1]]
h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, N))); l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, N)))
t = 1_700_000_000 // 14400 * 14400 + np.arange(N) * 14400.0
mk = lambda n: {"t": t[:n], "o": o[:n], "h": h[:n], "l": l[:n], "c": c[:n]}
K = 3; R = sd._rsi(c); ref = {}                                                                   # еталон: повний прохід, як у div_lab.py
for typ, x in (("L", l), ("H", h)):
    ext = (pd.Series(x).rolling(7, center=True).min() if typ == "L" else pd.Series(x).rolling(7, center=True).max()).to_numpy()
    piv = np.flatnonzero(ext == x); piv = piv[(piv >= 210) & (piv + K < N)]
    for p, q in zip(piv[:-1], piv[1:]):
        if q - p > 60 or q - p <= K: continue
        if typ == "L": kind = "RB" if (l[q] < l[p] and R[q] > R[p]) else ("HB" if (l[q] > l[p] and R[q] < R[p]) else None)
        else: kind = "RS" if (h[q] > h[p] and R[q] < R[p]) else ("HS" if (h[q] < h[p] and R[q] > R[p]) else None)
        if kind: ref.setdefault(q + K, set()).add(kind)
db = os.path.join(tempfile.mkdtemp(), "d.db"); seen = 0; kinds = set()
for n in range(240, N + 1):
    cs = sd.candidates(mk(n)); got = {x["kind"].split("_")[1] for x in cs}
    assert got == ref.get(n - 1, set()), (n, got, ref.get(n - 1))
    for x in cs:
        seen += 1; kinds.add(x["kind"]); risk = abs(x["entry"] - x["sl"]); m200 = c[n - 200:n].mean()
        assert abs(abs(x["tp"] - x["entry"]) - 6 * risk) < 1e-9 and x["side"] * (x["entry"] - x["sl"]) > 0 and x["kind"].endswith("T" if x["side"] * (x["entry"] - m200) > 0 else "A"), x
    sd.step(db, "TESTUSDT", mk(n), float(n))
rows = _fetchall(db, "SELECT sid, kind, status, r FROM sw_shadow", ())
assert seen >= 20 and len(kinds) >= 4 and rows and all(r[1].startswith("DIV_") for r in rows), (seen, kinds)
op = [r[1] for r in rows if r[2] == "OPEN"]; assert len(op) == len(set(op)) and any(r[2] in ("SL", "TP", "TIME") and r[3] is not None for r in rows)
os.environ["DIV_SHADOW"] = "0"; assert sd.step(os.path.join(tempfile.mkdtemp(), "d2.db"), "TESTUSDT", mk(500), 1.0) == []; os.environ["DIV_SHADOW"] = "1"
print("ok shadow div:", seen, "сигналів,", len(rows), "записів, види", sorted(kinds))
