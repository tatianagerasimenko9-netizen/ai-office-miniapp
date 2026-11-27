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

# --- сигнал «ВІДСКОК»: три зливи в те саме дно (±1 ATR), падіння >20% від 7-денного максимуму, BTC підтвердив → BN|… + BNC_S3
import json
from office_br import card, store
def series():
    px = [100.0] * 250
    def leg(a, b, n): return list(np.linspace(a, b, n + 1)[1:])
    px += leg(100, 78.3, 20) + leg(78.3, 82, 14) + leg(82, 78.2, 14) + leg(78.2, 82, 14) + leg(82, 78.0, 14) + [78.6, 79.4]
    c_ = np.array(px); o_ = np.r_[c_[0], c_[:-1]]; h_ = np.maximum(o_, c_) + 0.15; l_ = np.minimum(o_, c_) - 0.15; t_ = 1_700_000_000 // 3600 * 3600 + np.arange(len(c_)) * 3600.0
    return t_, h_, l_, c_
t2, h2, l2, c2 = series(); B2 = {"t": t2, "h": h2, "l": l2, "c": c2}; n2 = len(c2); en = sb.entry_at(B2, n2 - 1); assert en, "немає повернення на останньому барі"
k, drop = sb.depth(B2, en[0]); assert k >= 2 and drop > 20, (k, drop)
now2 = t2[-1] + 3600 + 50
def fetch2(sym, tf, limit, closed_only=True):
    if tf == "1h": return [{"ts": iso(t2[i]), "high": h2[i], "low": l2[i], "close": c2[i]} for i in range(max(0, n2 - limit), n2)]
    return [{"ts": iso(t2[0] - (260 - i) * 86400), "high": 120, "low": 90, "close": 100} for i in range(260)]
db = os.path.join(tempfile.mkdtemp(), "s.db"); store.init(db)
from office_bridge import _execute
_execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("SW|BTCUSDT|SHORT|1", 27, "BTCUSDT", "SHORT", 1, 1, 1, 1, 95.0, 101.0, "[]", "{}", now2 - 86400, "SENT"))
made = sb.scan(db, fetch2, now2, ("BTCUSDT", "ETHUSDT"))
assert sum(m.startswith("BN|") for m in made) == 2 and sum(m.startswith("BNC_S3|") for m in made) == 2, made
row = [r for r in store.rows(db, "WHERE sig_id LIKE 'BN|%'") if r["symbol"] == "BTCUSDT"][0]; hy = json.loads(row["hyp_json"])
assert row["status"] == "NEW" and card.is_td(row) and card.strat(row)[0] == "ВІДСКОК" and not card.is_swing(row) and abs(float(row["confirm_ts"]) - (t2[-1] + 2700)) < 1
assert "не закривати" in hy["opp"] and "№27" in hy["opp"] and "з 10" in hy["note"]
_execute(db, "UPDATE br_test_signal SET msg_id = 555 WHERE sig_id = 'SW|BTCUSDT|SHORT|1'", ()); hy["opp_msg"] = 555; row["hyp_json"] = json.dumps(hy, ensure_ascii=False); os.environ["OFFICE_CHAT_ID"] = "-1001234567890"
cap = card.build_caption(row)[0]; assert "ВІДСКОК №1" in cap and "на перевірці" not in cap and "тримати" not in cap and '<a href="https://t.me/c/1234567890/555">Шорт СВІНГ №27</a>' in cap and "дно тестували" in cap, cap
os.environ.pop("OFFICE_CHAT_ID"); assert "<a href" not in card.build_caption(row)[0] and "Шорт СВІНГ №27" in card.build_caption(row)[0]
assert sb.scan(db, fetch2, now2, ("BTCUSDT", "ETHUSDT")) == []                                                   # повторів немає
os.environ["BNC_LIVE"] = "0"; db3 = os.path.join(tempfile.mkdtemp(), "s3.db"); m3 = sb.scan(db3, fetch2, now2, ("BTCUSDT", "ETHUSDT")); os.environ["BNC_LIVE"] = "1"
assert m3 and all(m.startswith("BNC_S3|") for m in m3), m3                                                         # вимкнений сигнал → лише тихий журнал
print("ok bounce signal: тестів дна", k, f"падіння {drop:.1f}%"); print("--- картка ---"); print(cap)
