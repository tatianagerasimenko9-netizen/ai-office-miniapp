"""Офлайн-тести: вилучення ознак, строгі критерії стійкості, чесний train/test фільтр (без підгляду в тест)."""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from office2.learning import feature_study as FS
from office2.learning import features as FT

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if not cond else ""))
    if not cond:
        FAILS.append(name)


th = {"dir": "LONG", "kind": "SWEEP_SEQ", "level": {"kind": "NEW_YORK_L", "strength": 1}, "event": {"class": "LATE_SWEEP"}, "quality": {"risk_atr15": 3.7, "first_target_r": 1.2}, "sizing": {"stop_pct": 0.5},
      "integral": {"classification": "COUNTER", "counter_trend": True, "for": ["a"], "against": ["b", "c"]},
      "evidence": [{"module": "OB / FVG / OTE (premium-discount)", "supports": -1, "finding": "premium"}, {"module": "Gerchik mirror level + люфт", "supports": 1, "finding": "m"},
                   {"module": "Wyckoff (spring/upthrust, тест)", "supports": 0, "finding": "фаза не визначена"}]}
f = FT.extract(th, 1_791_688_858.0, {"btc_ret_1h": -0.3}, {"rs_vs_btc_1h": 0.0})
check("ознаки: клас рівня, LATE → не свіжий, pd проти, mirror, Wyckoff не визначено", f["lvl_class"] == "SESSION" and f["retest_not_fresh"] and f["pd"] == "AGAINST" and f["mirror_for"] and not f["wyckoff_defined"], str(f))
check("ознаки: BTC проти LONG, cost_heavy (0.15/0.5=0.3R), weekend", f["btc_1h"] == "AGAINST" and f["cost_heavy"] and f["weekend"] is True)
check("ознаки: бакети ризику/цілі", f["risk_atr"] == "≥3.0" and f["tp1_r"] == "<1.5", f["risk_atr"] + f["tp1_r"])

# синтетика: ознака A стабільно погана (-0.3R) в обох половинах; ознака B шум; решта ~0
rnd = random.Random(3)
rows = []
for i in range(600):
    a = rnd.random() < 0.3
    b = rnd.random() < 0.5
    r = (-0.3 if a else 0.02) + rnd.gauss(0, 0.9)
    rows.append({"source": "BRAIN", "ts_bar": i * 900, "symbol": "X", "variants": {"V0_current": {"r_net": r, "outcome": "TP1" if r > 0 else "SL"}},
                 "f": {"dir": "LONG" if i % 2 else "SHORT", "retest_not_fresh": a, "mirror_for": b, "kind": "SWEEP_SEQ"}})
st = FS.study(rows)
cells = {(c["feature"], c["value"]): c for c in st["all"]}
check("стійка негативна ознака виявлена", cells[("retest_not_fresh", "True")]["status"] == "STABLE_NEGATIVE", str(cells[("retest_not_fresh", "True")]))
check("шумова ознака не названа стійкою", cells[("mirror_for", "True")]["status"] == "NOT_STABLE" and cells[("dir", "LONG")]["status"] == "NOT_STABLE")
fl = st["oos_filter"]
check("фільтр з навчання покращує ТЕСТ", "retest_not_fresh=True" in fl["excluded_cells_from_train"] and fl["test_kept"]["mean_r"] > fl["test_all"]["mean_r"], str(fl))

# чисто шумові дані: нічого не стійке (захист від підгонки)
noise = [{"source": "BRAIN", "ts_bar": i * 900, "symbol": "X", "variants": {"V0_current": {"r_net": rnd.gauss(0, 1), "outcome": "TP1"}},
          "f": {"dir": rnd.choice(["LONG", "SHORT"]), "kind": rnd.choice(["A", "B"]), "session": rnd.choice(["ASIA", "LONDON", "NY", "OFF"]), "weekend": rnd.random() < 0.3}} for i in range(800)]
sn = FS.study(noise)
check("на шумі стійких клітинок немає", not sn["stable"], str(sn["stable"])[:200])
check("мало даних → INSUFFICIENT", FS.study(rows[:50])["status"] == "INSUFFICIENT")

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
