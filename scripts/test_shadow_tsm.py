"""Тихий журнал «тижнева карта монет» (офлайн): ваги, запис раз на тиждень, результат попереднього тижня, без дублювання."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from office_td import shadow_tsm as t
from office_bridge import _fetchall
U = t.universe(); assert len(U) == 42 and "XAUUSDT" not in U, len(U)
rng = np.random.default_rng(3); base = {}
for i, s in enumerate(U):
    drift = 0.004 if i % 2 == 0 else -0.004                         # парні ростуть, непарні падають
    base[s] = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.002 * (1 + i % 3), 120)))
day = {"n": 100}
def fetch(sym, tf, n, closed_only=True):
    assert tf == "1d"; c = base[sym][:day["n"]][-n:]
    return [{"close": float(x), "volume": 1000.0 * (50 - U.index(sym))} for x in c]
db = os.path.join(tempfile.mkdtemp(), "t.db"); mon = t.MON0 + 2900 * t.WEEK
assert t.cycle(db, fetch, mon + 300) is None                          # перші 10 хв після півночі чекаємо
t._LAST_TRY = 0; r1 = t.cycle(db, fetch, mon + 3600); assert r1 and r1["n_long"] + r1["n_short"] == 20 and r1["usd_prev"] is None, r1
w = __import__("json").loads(_fetchall(db, "SELECT weights_json FROM tsm_shadow_week", ())[0][0])
assert abs(sum(abs(x) for x in w.values()) - 1) < 1e-9 and all((w[s] > 0) == (U.index(s) % 2 == 0) for s in w), w   # напрям = знак 30-денної зміни; сума модулів 1
assert len(w) == 20                                                   # топ-20 за обсягом
t._LAST_TRY = 0; assert t.cycle(db, fetch, mon + 7200) is None        # той самий тиждень: без дубля
day["n"] = 107; t._LAST_TRY = 0; r2 = t.cycle(db, fetch, mon + t.WEEK + 3600)
assert r2 and r2["usd_prev"] is not None and r2["usd_prev"] > 0, r2   # ваги за трендом на трендових даних → плюс
assert len(_fetchall(db, "SELECT 1 FROM tsm_shadow_week", ())) == 2
os.environ["TSM_SHADOW"] = "0"; t._LAST_TRY = 0; assert t.cycle(db, fetch, mon + 2 * t.WEEK + 3600) is None; os.environ["TSM_SHADOW"] = "1"
print("ok shadow tsm")
