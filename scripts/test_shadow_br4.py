"""Тихий журнал BR4 (офлайн): сигнал детектора B&R на щойно закритому H4-барі лише за трендом MA200, стоп ×3, ціль 3R; запис без повідомлень, одна відкрита на монету, закриття, вимикач."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from office_br import detect
from office_td import shadow_br4 as sh
from office_bridge import _fetchall
rng = np.random.default_rng(3); N = 700
c = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.012, N))); o = np.r_[c[0], c[:-1]]
h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, N))); l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, N)))
t = 1_700_000_000 // 14400 * 14400 + np.arange(N) * 14400.0
mk = lambda n: {"t": t[:n], "o": o[:n], "h": h[:n], "l": l[:n], "c": c[:n]}
full = detect.scan(list(t), list(o), list(h), list(l), list(c))                                   # еталон: повний прохід детектора
db = os.path.join(tempfile.mkdtemp(), "b.db"); found = []; nsig = 0
for n in range(230, N + 1):
    cd = sh.candidate(mk(n))
    ref = [s for s in full if s["confirm_i"] == n - 1]
    m200 = c[n - 200:n].mean()
    if cd:
        nsig += 1; s = ref[-1]; side = 1 if s["direction"] == "LONG" else -1                      # той самий сигнал, що в повному проході
        assert cd["side"] == side and abs(cd["entry"] - s["entry"]) < 1e-9 and side * (c[n - 1] - m200) > 0, (n, cd, s)
        assert abs(abs(cd["entry"] - cd["sl"]) - 3 * s["risk"]) < 1e-9 and abs(abs(cd["tp"] - cd["entry"]) - 9 * s["risk"]) < 1e-9, cd
    else:
        assert not any((1 if s["direction"] == "LONG" else -1) * (c[n - 1] - m200) > 0 for s in ref[-1:]), (n, ref)    # сигнал за трендом не пропущено
    sid = sh.step(db, "TESTUSDT", mk(n), float(n))
    if sid: found.append(sid)
assert nsig >= 3 and found and all(x.startswith("BR4|TESTUSDT|") for x in found), (nsig, found)
rows = _fetchall(db, "SELECT sid, status, r, kind FROM sw_shadow", ())
assert all(r[3] == "BR4" for r in rows) and sum(r[1] == "OPEN" for r in rows) <= 1 and any(r[1] in ("SL", "TP", "TIME") and r[2] is not None for r in rows), rows
assert len({r[0] for r in rows}) == len(rows)
os.environ["BR4_SHADOW"] = "0"; assert sh.step(os.path.join(tempfile.mkdtemp(), "b3.db"), "TESTUSDT", mk(400), 1.0) is None; os.environ["BR4_SHADOW"] = "1"
print("ok shadow br4", nsig, "сигналів;", len(rows), "записів")
