"""Офлайн-перевірка entry_quality_study на синтетичних даних: статистика рекавері/причин/кластерів і вердикт альтернатив."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
root = Path(__file__).resolve().parent
bad = 0
def check(n, ok):
    global bad
    print(("OK   " if ok else "FAIL ") + n); bad += 0 if ok else 1
d = Path(tempfile.mkdtemp())
for per in ("A", "D"):
    (d / f"eq-{per}-X").mkdir()
    cf = []
    for i in range(120):
        sl = i % 2 == 0
        q = {"o": "SL" if sl else "TP1", "r": -1.05 if sl else 1.1, "ts_sl": 1000.0 + 600 * i, "deeper": sl and i % 4 == 0, "tp1_24h": sl and i % 4 == 0, "tp1_72h": sl and i % 4 == 0,
             "cls": ("PREMATURE_ENTRY" if i % 4 == 0 else "WRONG_DIRECTION") if sl else None,
             "alt": {"E2": {"o": "TP1", "r": 0.9}, "SG": {"o": "SL", "r": -1.2}, "SA": {"o": "SL", "r": -1.3}}}
        cf.append({"source": "BRAIN", "symbol": f"S{i % 9}", "ts_bar": 1000 + 900 * i, "dir": "LONG", "q": q, "f": {"retest_not_fresh": i % 3 == 0, "lvl_class": "SESSION"},
                   "tactics": {"T3_limit_zone_mid": {"r_net": 0.2}}})
    (d / f"eq-{per}-X" / "o.json").write_text(json.dumps({"counterfactual_rows": cf}))
r = subprocess.run([sys.executable, str(root / "entry_quality_study.py"), str(d)], capture_output=True, text=True)
check("скрипт завершився", r.returncode == 0)
check("рекавері 24 год пораховано (50% SL з відновленням)", "TP1 досягнуто за 24 год — 50.0%" in r.stdout)
check("E2 допустимо за синтетичним ефектом", "E2 лімітний вхід на дальньому краї зони: ДОПУСТИМО ДЛЯ SHADOW" in r.stdout)
check("SG гірше → не підтверджено", "SG SL=екстремум−20% стопа (Герчик-подібний): НЕ ПІДТВЕРДЖЕНО" in r.stdout)
sys.exit(1 if bad else 0)
