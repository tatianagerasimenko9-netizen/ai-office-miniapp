"""Офлайн-перевірка replay_market_context_study на синтетичних даних: конкурентність без look-ahead, правила, вердикт."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
import replay_market_context_study as S

bad = 0
def check(n, ok):
    global bad
    print(("OK   " if ok else "FAIL ") + n); bad += 0 if ok else 1

H = 3600.0
rows = [{"per": "A", "sym": s, "ts": t, "dir": "LONG", "sess": "LONDON", "btc": "WITH", "rs": "FLAT", "out": "SL", "r": -1.0, "conc_prior": 0} for s, t in (("X", 0), ("Y", 1 * H), ("Z", 2 * H), ("X", 3 * H), ("W", 9 * H))]
S.add_concurrency(rows)
check("перший сигнал без попередніх", rows[0]["conc_prior"] == 0)
check("другий бачить лише попередній (не майбутні)", rows[1]["conc_prior"] == 1)
check("третій бачить двох", rows[2]["conc_prior"] == 2)
check("та сама монета не рахується собі", rows[3]["conc_prior"] == 2)
check("за межею вікна — 0", rows[4]["conc_prior"] == 0)

d = Path(tempfile.mkdtemp())
for per, n in (("A", 80), ("D", 80)):
    (d / f"replay-{per}-X").mkdir()
    cf = []
    for i in range(n):
        bad_ctx = i % 2 == 0   # «погані» — btc AGAINST: гірший R
        cf.append({"source": "BRAIN", "symbol": f"S{i % 7}", "ts_bar": 1000 + 900 * i, "dir": "LONG", "f": {"session": "ASIA", "btc_1h": "AGAINST" if bad_ctx else "WITH", "rs_1h": "FLAT"},
                   "variants": {"V0_current": {"outcome": "SL" if bad_ctx else "TP1", "r_net": -1.0 if bad_ctx else 0.8}}})
    (d / f"replay-{per}-X" / "out_X.json").write_text(json.dumps({"counterfactual_rows": cf}))
r = subprocess.run([sys.executable, str(root / "replay_market_context_study.py"), str(d)], capture_output=True, text=True)
check("скрипт завершився", r.returncode == 0)
check("R3 підтверджене на синтетичному ефекті", "R3_btc_against: ДОПУСТИМО ДЛЯ SHADOW" in r.stdout)
check("R2 без даних не підтверджується", "R2_conc>=2: ДОПУСТИМО" not in r.stdout)
sys.exit(1 if bad else 0)
