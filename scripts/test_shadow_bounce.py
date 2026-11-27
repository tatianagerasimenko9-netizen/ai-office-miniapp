"""Тихий журнал «відскок після зливу» (офлайн): вхід на останньому барі збігається з еталонним проходом (як у bounce_lab.py); запис лише за умов B+L+T; вид U/N за денним трендом BTC; без повідомлень."""
import os, sys, tempfile
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from office_td import shadow_bounce as sb
from office_bridge import _fetchall
rng = np.random.default_rng(5); N = 1500
c = 100 * np.exp(np.cumsum(rng.standard_t(3, N) * 0.006)); o = np.r_[c[0], c[:-1]]
h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, N))); l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, N))); t = 1_700_000_000 // 3600 * 3600 + np.arange(N) * 3600.0
B = {"t": t, "h": h, "l": l, "c": c}; fl = sb.flushes(B); A = sb._atr(B); ref = {}
for f in fl:                                                     # еталон: прохід уперед від кожного зливу, як у bounce_lab.py
    for j in range(f + 1, min(N, f + 1 + sb.WAIT)):
        if l[j] < l[f]: break
        if c[j] > h[f]: ref.setdefault(j, f); break
cut = lambda n: {k: v[:n] for k, v in B.items()}; seen = 0
for n in range(300, N + 1):
    en = sb.entry_at(cut(n), n - 1); j = n - 1
    if j in ref and 0.0005 <= (c[j] - (l[ref[j]] - 0.1 * A[j])) / c[j] <= 0.25:
        assert en and abs(en[1] - c[j]) < 1e-9 and en[2] < l[en[0]] <= l[j], (n, en); seen += 1
    else: assert en is None or j in ref, (n, en)
assert seen >= 5, seen
# сценарій запису: 12 монет з однаковими барами (ширина 100%), BTC серед них; денний рівень проколото
j = sorted(ref)[len(ref) // 2]; f = ref[j]; n = j + 1; now = t[j] + 3600 + 50
iso = lambda x: datetime.fromtimestamp(x, timezone.utc).isoformat()
def fetch_factory(up):
    def fetch(sym, tf, limit, closed_only=True):
        if tf == "1h": return [{"ts": iso(t[i]), "high": h[i], "low": l[i], "close": c[i]} for i in range(max(0, n - limit), n)]
        days = 260; base = (t[f] // 86400) * 86400 - np.arange(days, 0, -1) * 86400.0; lv = (l[f] + c[j]) / 2; lows = np.full(days, lv * 1.5); lows[-10] = lv   # свінг-мінімум 10 діб тому між дном зливу і входом
        cl = np.linspace(50, 300, days) if up else np.linspace(300, 50, days)
        return [{"ts": iso(base[i]), "high": lows[i] * 1.1, "low": lows[i], "close": cl[i] if sym == "BTCUSDT" else lows[i] * 1.05} for i in range(days)]
    return fetch
syms = ("BTCUSDT",) + tuple(f"C{i}USDT" for i in range(11))
for up, kind in ((True, "BNC_U"), (False, "BNC_N")):
    db = os.path.join(tempfile.mkdtemp(), "b.db"); made = sb.scan(db, fetch_factory(up), now, syms)
    assert len(made) == 12 and all(m.startswith(kind + "|") for m in made), (kind, made)
    assert sb.scan(db, fetch_factory(up), now, syms) == []                      # один відкритий запис на монету
    r = _fetchall(db, "SELECT entry, sl, tp, status FROM sw_shadow", ()); assert all(abs((x[2] - x[0]) - 3 * (x[0] - x[1])) < 1e-9 and x[3] == "OPEN" for x in r)
db = os.path.join(tempfile.mkdtemp(), "b.db"); assert sb.scan(db, fetch_factory(True), now, syms[:5]) == []     # замало монет для ширини
os.environ["BNC_SHADOW"] = "0"; assert sb.scan(db, fetch_factory(True), now, syms) == []; os.environ["BNC_SHADOW"] = "1"
print("ok shadow bounce:", seen, "входів звірено з еталоном")
