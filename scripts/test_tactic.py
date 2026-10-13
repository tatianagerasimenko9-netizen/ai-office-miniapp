#!/usr/bin/env python3
"""Тактики відносно перешкоди: арифметика R, порядок подій (SL перед TP в одному барі), пропуски, контролі, рекомендація з таблиці."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import tactic as TC  # noqa: E402

fails = []
def check(n, c):
    if not c:
        fails.append(n); print("FAIL", n)

def bars(h, l, c):
    n = len(h)
    return {"t": np.arange(n) * 900.0, "o": np.array(c, float), "h": np.array(h, float), "l": np.array(l, float), "c": np.array(c, float), "v": np.ones(n), "tbv": np.ones(n)}

EV = {"dir": "LONG", "entry": 100.0, "sl": 99.0, "tp1": 103.0, "zone": [99.2, 99.9], "obst": [{"p": 101.0, "r": 1.0}], "sl_v2": 99.4}
# бар0 — рішення. Ціна доходить до 101.2 (перешкода) і розвертається до входу, не досягнувши TP1.
m = bars([100, 101.2, 100.5, 100.2, 100.1], [100, 100.1, 99.8, 99.7, 99.6], [100, 101.0, 100.0, 100.0, 99.9])
t0 = TC.t0(m, 0, EV); t1 = TC.t1_scalp(m, 0, EV)
check("T0: без TP1 → OPEN (за ціною горизонту)", t0["outcome"] == "OPEN")
check("T1: скальп бере перешкоду (TP1 у термінах цілі=перешкода)", t1["outcome"] == "TP1" and 0.7 < t1["r_net"] < 1.0)   # 1R мінус витрати
# T2: пробій перешкоди закриттям > 101 → вхід після пробою
m2 = bars([100, 100.9, 101.6, 103.5], [100, 100.2, 100.9, 101.5], [100, 100.8, 101.5, 103.2])
t2 = TC.t2_wait_break(m2, 0, EV)
check("T2: вхід на закритті за перешкодою, далі TP1", t2["outcome"] == "TP1")
# T2: SL раніше пробою → пропуск
m3 = bars([100, 100.5, 101.2], [100, 98.9, 100.0], [100, 99.5, 101.1])
check("T2: SL до пробою → MISSED", TC.t2_wait_break(m3, 0, EV)["outcome"] == "MISSED_SL_BEFORE_BREAK")
# T2: пробою нема
m4 = bars([100] + [100.5] * 9, [100] + [99.5] * 9, [100] + [100.2] * 9)
check("T2: без пробою → MISSED", TC.t2_wait_break(m4, 0, EV)["outcome"] == "MISSED_NO_BREAK")
# T3: ліміт у середині зони 99.55
m5 = bars([100, 100.0, 103.5], [100, 99.5, 99.6], [100, 99.7, 103.2])
t3 = TC.t3_limit_mid(m5, 0, EV)
check("T3: заповнення на середині зони і TP1", t3["outcome"] == "TP1" and t3["r_net"] > 3.0)      # більше R, ніж T0 (3R) при тому ж SL/TP
m6 = bars([100, 103.5], [100, 99.95], [100, 103.0])
check("T3: TP1 раніше fill → MISSED", TC.t3_limit_mid(m6, 0, EV)["outcome"] == "MISSED_TP_BEFORE_FILL")
# T4: SL 99.4 ближче → той самий вихід дає більше R
m7 = bars([100, 103.5], [100, 99.9], [100, 103.2])
check("T4: коротший SL збільшує R", TC.t4_tight_sl(m7, 0, EV)["r_net"] > TC.t0(m7, 0, EV)["r_net"])
check("T4: без sl_v2 = T0", TC.t4_tight_sl(m7, 0, dict(EV, sl_v2=None))["r_net"] == TC.t0(m7, 0, EV)["r_net"])
check("T4: SL далі за поточний ігнорується", TC.t4_tight_sl(m7, 0, dict(EV, sl_v2=98.0))["r_net"] == TC.t0(m7, 0, EV)["r_net"])
# SL і TP в одному барі → SL
m8 = bars([100, 103.5], [100, 98.5], [100, 100])
check("SL перед TP в одному барі", TC.t0(m8, 0, EV)["outcome"] == "SL" and TC.t1_scalp(m8, 0, EV)["outcome"] == "SL")
# контролі
m9 = bars([100, 100.5], [100, 96.5], [100, 97])         # ціна пішла вниз: база (LONG) отримала б SL, дзеркальний SHORT — ціль
c1 = TC.c1_mirror(m9, 0, EV)
check("C1: дзеркальний напрям дає ціль там, де база SL", TC.t0(m9, 0, EV)["outcome"] == "SL" and c1["outcome"] == "TP1" and c1["r_net"] > 2.5)
atr = np.full(len(m["t"]), 1.0)
check("C2: контроль рахується", TC.c2_momentum(bars([100] * 8, [99] * 8, [100, 100, 100, 100, 101, 101, 101, 101]), 5, EV, np.full(8, 1.0))["outcome"] in ("TP1", "SL", "OPEN", "NO_DATA"))
# корзини
check("бакет NO_OBSTACLE", TC.bucket({}) == "NO_OBSTACLE")
check("бакет <0.5R", TC.bucket({"obst": [{"p": 1, "r": 0.4}]}) == "OBST_LT_0.5R")
check("бакет 0.5–1R", TC.bucket({"obst": [{"p": 1, "r": 0.63}]}) == "OBST_0.5_1R")
check("бакет ≥1R", TC.bucket({"obst": [{"p": 1, "r": 1.0}]}) == "OBST_GE_1R")
# рекомендація: LINK-подібний (0.63R) і TIA-подібний (0.87R)
th = {"dir": "SHORT", "entry": 12.904, "sl": 13.122, "targets": [{"p": 12.249, "r": 3.0}], "obstacles_before_tp1": [{"p": 12.766, "r": 0.633}], "entry_zone": [12.944, 13.0239], "stops": {"v2": {"sl": 13.1086}}}
a = TC.advise(th)
check("advise: без таблиці → T0, R розраховані для T1", a["tactic"] == "T0_enter_now" and not a["table_used"] and a["options"]["T1_scalp_to_obstacle"]["r_to_tp"] == round((12.904 - 12.766) / 0.218, 2))
check("advise: T3 для SHORT — вище за вхід", "T3_limit_zone_mid" in a["options"] and a["options"]["T3_limit_zone_mid"]["entry"] > th["entry"])
check("advise: T4 коротший SL", a["options"]["T4_tight_structural_sl"]["r_to_tp"] > a["options"]["T0_enter_now"]["r_to_tp"])
b = TC.advise(th, {"OBST_0.5_1R": "T2_wait_break"})
check("advise: таблиця вибирає тактику для корзини", b["tactic"] == "T2_wait_break" and b["table_used"])
check("advise: порожні дані безпечні", TC.advise({})["tactic"] == "T0_enter_now")
print("OK" if not fails else f"FAIL: {fails}")
sys.exit(1 if fails else 0)
