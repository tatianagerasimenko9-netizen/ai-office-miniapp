"""Тихий журнал EW3 (офлайн): сигнал на барі підтвердження пивота, запис без повідомлень, закриття по стопу/цілі/часу."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from office_td import shadow_wave as sh
from office_bridge import _fetchall
def mk(c):
    c = np.array(c, float); t = 1_700_000_000 // 14400 * 14400 + np.arange(len(c)) * 14400.0
    return {"t": t, "o": np.r_[c[0], c[:-1]], "h": c + 0.2, "l": c - 0.2, "c": c}
base = list(100 + 0.05 * np.arange(230))                       # плавний тренд вгору (вище MA200), ATR ≈ 0,4
up1 = [base[-1] + 2 * k for k in range(1, 6)]                  # хвиля 1: +10
dn2 = [up1[-1] - 1.2 * k for k in range(1, 5)]                 # хвиля 2: −4,8 (не заходить за початок)
turn = [dn2[-1] + 1.0 * k for k in range(1, 7)]                # розворот угору: підтверджує мінімум P2
series = base + up1 + dn2 + turn
db = os.path.join(tempfile.mkdtemp(), "s.db"); found = None
for n in range(len(base) + len(up1), len(series) + 1):
    sid = sh.step(db, "TESTUSDT", mk(series[:n]), 1.0)
    if sid: found = (sid, n); break
assert found and found[0].startswith("EW3|TESTUSDT|LONG|"), found
row = _fetchall(db, "SELECT direction, entry, sl, tp, status FROM sw_shadow", ())[0]
assert row[0] == "LONG" and row[2] < row[1] < row[3] and row[4] == "OPEN", row
assert sh.step(db, "TESTUSDT", mk(series[:found[1]]), 2.0) is None                                # повторно не записує, одна відкрита на монету
more = series[:found[1]] + [series[found[1] - 1] + 3 * k for k in range(1, 12)]                 # далі ціна йде до цілі
sh.step(db, "TESTUSDT", mk(more), 3.0)
st = _fetchall(db, "SELECT status, r FROM sw_shadow", ())[0]; assert st[0] == "TP" and st[1] > 0, st
db2 = os.path.join(tempfile.mkdtemp(), "s2.db"); sh.step(db2, "TESTUSDT", mk(series[:found[1]]), 1.0)
sh.step(db2, "TESTUSDT", mk(series[:found[1]] + [series[found[1] - 1] - 6 * k for k in range(1, 6)]), 2.0)
st = _fetchall(db2, "SELECT status, r FROM sw_shadow", ())[0]; assert st[0] == "SL" and st[1] < -1, st
os.environ["SW_SHADOW"] = "0"; assert sh.step(os.path.join(tempfile.mkdtemp(), "s3.db"), "TESTUSDT", mk(series[:found[1]]), 1.0) is None; os.environ["SW_SHADOW"] = "1"
print("ok shadow wave")
