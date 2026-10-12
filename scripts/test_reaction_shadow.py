"""reaction_shadow: TOUCH → REACT → CONFIRM на закритих барах, без lookahead, SL-скасування, вхід на open наступного бару, SHORT-дзеркало. Офлайн."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import reaction_shadow as RS  # noqa: E402

FAILS = []


def check(n, ok, info=""):
    print(("OK  " if ok else "FAIL"), n, "" if ok else info)
    if not ok:
        FAILS.append(n)


T0 = 1_791_720_000 - (1_791_720_000 % 900)
M = 900


def bar(i, o, h, l, c):
    return {"ts": T0 + i * M, "open": o, "high": h, "low": l, "close": c}


card = {"card_id": "W|X", "symbol": "XUSDT", "direction": "LONG", "created_ts": T0, "expires_ts": T0 + 40 * M, "zone_lo": 99.0, "zone_hi": 100.0, "entry": 100.0, "sl": 97.0, "tp1": 106.0, "risk_pct": 3.0}
now = T0 + 30 * M
# 0: ціна вище зони (без торкання); 1: торкання зони (low 99.5), закриття нижче open; 2: бичача, закриття 100.8 > zone_hi → REACT; 3: підтвердження (low 100.3 ≥ low REACT 99.9, бичача); 4: ціна росте; 5: TP1
bars = [bar(0, 103, 103.5, 101, 102), bar(1, 102, 102.2, 99.5, 99.8), bar(2, 99.9, 101.0, 99.9, 100.8), bar(3, 100.8, 101.8, 100.3, 101.5), bar(4, 101.5, 104, 101.4, 103.5), bar(5, 103.5, 107, 103.0, 106.5)]
ev = RS.find_events(card, bars, now)
check("TOUCH на барі 1, REACT на барі 2, CONFIRM на барі 3", (ev["touch"], ev["react"], ev["confirm"]) == (1, 2, 3), ev)
r = RS.evaluate(card, bars, now)
v1, v2 = r["V1_react"], r["V2_react_confirm"]
check("V1 входить на open бару 3 (100.8), V2 — на open бару 4 (101.5)", v1["entry"] == 100.8 and v2["entry"] == 101.5, (v1, v2))
check("TP1 досягнуто, R = RR − витрати(0): V1 1.5", v1["status"] == "TP1" and abs(v1["r_net"] - round((106 - 100.8) / 3.8, 3)) < 1e-6, v1)
check("пізніший вхід має гірший RR до цілі", v2["rr_to_tp1"] < v1["rr_to_tp1"], (v1["rr_to_tp1"], v2["rr_to_tp1"]))

# без lookahead: на as_of до закриття бару 3 CONFIRM ще немає
ev2 = RS.find_events(card, bars, T0 + 3 * M)
check("на as_of=T0+3 бар 3 ще не закрито → CONFIRM немає", ev2["confirm"] is None and ev2["react"] == 2, ev2)

# скасування: low ≤ SL до реакції
bad = [bar(0, 103, 103.5, 101, 102), bar(1, 102, 102.2, 96.5, 97.0), bar(2, 97, 101, 96.8, 100.9)]
evb = RS.find_events(card, bad, now)
check("low ≤ SL до входу → скасовано, входу немає", evb["cancelled"] is not None and evb["react"] is None, evb)
check("evaluate: НЕМАЄ_ВХОДУ при скасуванні", RS.evaluate(card, bad, now)["V1_react"]["status"] == "НЕМАЄ_ВХОДУ")

# реакція скасована наступною свічкою (low нижче low REACT) → CONFIRM не наступає на цьому барі
weak = [bar(0, 103, 103.5, 101, 102), bar(1, 102, 102.2, 99.5, 99.8), bar(2, 99.9, 101.0, 99.9, 100.8), bar(3, 100.8, 100.9, 99.7, 100.0)]
evw = RS.find_events(card, weak, now)
check("наступна свічка зламала low REACT → CONFIRM немає", evw["react"] == 2 and evw["confirm"] is None, evw)

# ціна вже за ціллю на вході → пропущено
late = [bar(0, 103, 103.5, 101, 102), bar(1, 102, 102.2, 99.5, 99.8), bar(2, 99.9, 101.0, 99.9, 100.8), bar(3, 107, 108, 106.5, 107.5)]
check("відкриття бару входу вище TP1 → ПРОПУЩЕНО_ЦІНА_ПОЗА_ПЛАНОМ", RS.simulate_entry(card, late, 3)["status"] == "ПРОПУЩЕНО_ЦІНА_ПОЗА_ПЛАНОМ")

# SL у барі входу першим
sl_first = [bar(0, 100.8, 107, 96.0, 100.0)]
check("SL і TP в одному барі → SL першим", RS.simulate_entry(card, sl_first, 0)["status"] == "SL")

# дзеркало SHORT
sc = dict(card, direction="SHORT", zone_lo=100.0, zone_hi=101.0, entry=100.0, sl=103.0, tp1=94.0)
sb = [bar(0, 97, 99, 96.5, 98), bar(1, 98, 100.5, 97.8, 100.2), bar(2, 100.1, 100.2, 99.0, 99.2), bar(3, 99.2, 99.7, 98.0, 98.5), bar(4, 98.5, 98.6, 93.0, 94.0)]
evs = RS.find_events(sc, sb, now)
check("SHORT: TOUCH 1, REACT 2, CONFIRM 3", (evs["touch"], evs["react"], evs["confirm"]) == (1, 2, 3), evs)
check("SHORT: V1 вхід на open бару 3, TP1", RS.evaluate(sc, sb, now)["V1_react"]["status"] == "TP1")

# супровід угоди триває після expires_ts, вхід — лише до нього
c_exp = dict(card, expires_ts=T0 + 6 * M)
bars_long = bars + [bar(6, 106.5, 107, 106.0, 106.8)]
rx = RS.evaluate(c_exp, bars_long, now)
check("вхід до expires_ts, TP1 після expires_ts зараховується", rx["V1_react"]["status"] == "TP1", rx["V1_react"])
c_exp2 = dict(card, expires_ts=T0 + 3 * M)
check("бар входу після expires_ts → строк картки минув", RS.evaluate(c_exp2, bars_long, now)["V1_react"]["status"] == "НЕМАЄ_ВХОДУ")

# позначка гіпотези
check("результат маркований RESEARCH_HYPOTHESIS", r["label"] == "RESEARCH_HYPOTHESIS")

# витрати: cost_r_fn зменшує R
r2 = RS.evaluate(card, bars, now, lambda rp: 0.1)
check("витрати віднімаються від R", abs(r2["V1_react"]["r_net"] - (r["V1_react"]["r_net"] - 0.1)) < 1e-6)

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
