#!/usr/bin/env python3
"""office2/topdown: M5/M1 підтвердження входу (лише закриті бари, без майбутнього), тип сценарію, суперечності за типом."""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import topdown as TD  # noqa: E402

bad = []


def check(n, c):
    if not c:
        bad.append(n)
        print("FAIL", n)


T = 1_800_000_000.0                       # now: кратне 900
ZONE, SL = [100.0, 102.0], 99.0


def bars(spec, t0, w):
    """spec: список (o,h,l,c); бар i відкривається о t0+i*w."""
    a = np.array(spec, float)
    return {"t": t0 + np.arange(len(a)) * w, "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}


# M5: 12 барів до now (кожен закритий). Контакт: бар №6 (low 101.5 ≤ 102). Підтвердження: бар №8 закрився вище max high з моменту контакту (103.5).
m5_spec = [(105, 105.5, 104.5, 105)] * 6 + [(103, 103.5, 101.5, 102.5), (102.5, 103.0, 102.3, 102.8), (102.8, 104.0, 102.7, 103.8), (103.8, 104.2, 103.6, 104.0), (104.0, 104.3, 103.9, 104.1), (104.1, 104.5, 104.0, 104.4)]
m5 = bars(m5_spec, T - 12 * 300, 300)
# M1: після закриття M5-бару №8 (T-12*300+9*300 = T-900): 15 барів; ретест 103.5 на 4-му, закриття вище на 5-му.
m1_spec = [(103.9, 104.0, 103.8, 103.9)] * 4 + [(103.9, 104.0, 103.4, 103.45), (103.45, 103.9, 103.4, 103.8)] + [(103.8, 104.2, 103.7, 104.1)] * 9
m1 = bars(m1_spec, T - 900, 60)

r = TD.ltf_confirm("LONG", ZONE, SL, T, m5, m1)
check("LONG: M5 CONFIRMED", r["status"] == "CONFIRMED")
check("LONG: ref = max high з моменту контакту (103.5)", r["m5"] and abs(r["m5"]["ref_level"] - 103.5) < 1e-9)
check("LONG: час підтвердження = закриття бару №8", r["m5"] and r["m5"]["confirm_ts"] == T - 12 * 300 + 9 * 300)
check("LONG: M1 ретест → точка входу = закриття після повернення (103.8)", r["m1"]["state"] == "RETEST_ENTRY" and abs(r["m1"]["entry_price"] - 103.8) < 1e-9)

# --- без майбутнього: бари, що відкриваються ≥ now, та бар, що формується, ігноруються
fut = bars(m5_spec[:8] + [(102.8, 104.0, 102.7, 103.8)], T - 12 * 300, 300)     # 9-й бар відкривається о T-12*300+8*300 = T-1200 → закритий; зробимо його майбутнім:
fut["t"][-1] = T                                                               # відкривається в now → не закритий
p = TD.ltf_confirm("LONG", ZONE, SL, T, fut, m1)
check("бар, що відкривається в now, не рахується: підтвердження немає (PENDING)", p["status"] == "PENDING")
forming = bars(m5_spec[:6] + [(103, 103.5, 101.5, 102.5), (102.5, 103.0, 102.3, 102.8)] + [(102.8, 104.0, 102.7, 103.8)], T - 9 * 300, 300)
forming["t"][-1] = T - 150                                                      # відкрився 150 с тому: ще формується
f = TD.ltf_confirm("LONG", ZONE, SL, T, forming, m1)
check("бар, що формується (open+300 > now), не рахується", f["status"] == "PENDING")
full = TD.ltf_confirm("LONG", ZONE, SL, T + 3600, m5, m1)
check("той самий M5 у пізніший момент now (вікно змістилось) не бачить старого дотику", full["status"] in ("NOT_IN_ZONE", "PENDING", "UNAVAILABLE"))

# --- інші статуси
far = bars([(105, 105.5, 104.5, 105)] * 12, T - 12 * 300, 300)
check("NOT_IN_ZONE: low не торкнувся зони", TD.ltf_confirm("LONG", ZONE, SL, T, far, m1)["status"] == "NOT_IN_ZONE")
pend = bars([(105, 105.5, 104.5, 105)] * 10 + [(103, 103.5, 101.5, 102.5), (102.5, 103.0, 102.3, 102.8)], T - 12 * 300, 300)
check("PENDING: дотик є, мікро-зламу немає", TD.ltf_confirm("LONG", ZONE, SL, T, pend, m1)["status"] == "PENDING")
broken = bars([(105, 105.5, 104.5, 105)] * 10 + [(103, 103.5, 98.0, 98.5), (98.5, 104.0, 98.4, 103.8)], T - 12 * 300, 300)
check("SL торкнуто на M5 у вікні → INVALID, підтвердження немає", TD.ltf_confirm("LONG", ZONE, SL, T, broken, m1)["status"] == "INVALID")
check("без M5 → UNAVAILABLE", TD.ltf_confirm("LONG", ZONE, SL, T, None, m1)["status"] == "UNAVAILABLE")
no_ret = bars([(103.9, 104.0, 103.8, 103.9)] * 15, T - 900, 60)
check("M1 без ретесту → WAIT_RETEST із лімітним рівнем", TD.ltf_confirm("LONG", ZONE, SL, T, m5, no_ret)["m1"]["state"] == "WAIT_RETEST")
check("M1 недоступні → UNAVAILABLE, M5 лишається CONFIRMED", TD.ltf_confirm("LONG", ZONE, SL, T, m5, None)["m1"]["state"] == "UNAVAILABLE")

# --- SHORT: дзеркало (ціни ×(−1), high↔low)
def mir(b):
    return {"t": b["t"], "o": -b["o"], "h": -b["l"], "l": -b["h"], "c": -b["c"]}


rs = TD.ltf_confirm("SHORT", [-102.0, -100.0], -99.0, T, mir(m5), mir(m1))
check("SHORT: дзеркальний сценарій дає той самий статус", rs["status"] == "CONFIRMED" and abs(rs["m5"]["ref_level"] + 103.5) < 1e-9 and abs(rs["m1"]["entry_price"] + 103.8) < 1e-9)

# --- тип сценарію і суперечності
def th(d1="N", h4="N", h1="N", zone4="discount", proof=False, loc="HTF", long_=True, retest=False):
    def row(tf, s, zone=None):
        return {"tf": tf, "status": "USED", "trend_eff": 0, "with_trade": s == "W", "against_trade": s == "A", "zone": zone or "discount", "last_swing_high": 2.0, "last_swing_low": 1.0, "range": {"lo": 1.0, "hi": 2.0}, "closed_ts": T}
    return {"dir": "LONG" if long_ else "SHORT", "map": {"tfs": [row("W1", "N"), row("D1", d1), row("H4", h4, zone4), row("H1", h1)]},
            "integral": {"proof_h1": proof, "location": {"class": loc}, "level_retest_after_acceptance": retest}, "entry_zone": ZONE, "sl": SL, "sequence": [{"ok": True}]}


ada = th(d1="N", h4="N", h1="A", zone4="discount", retest=True)
t_ada = TD.scenario_type(ada)
check("ADA-подібний: D1/H4 діапазон → RANGE, вхід від правильної межі (discount для LONG)", t_ada["type"] == "RANGE" and t_ada["edge_ok"] is True)
c_ada = TD.conflicts(ada, t_ada)
check("ADA: H1 проти показано як warn (доказу H1 немає)", any(c["tf"] == "H1" and c["severity"] == "warn" for c in c_ada))
check("ADA: LATE_SWEEP показано як info", any("прийнятого рівня" in c["text"] for c in c_ada))
check("кожна суперечність має пояснення, чому допущено", all(c.get("why_allowed") for c in c_ada))
check("CONTINUATION: D1 за", TD.scenario_type(th(d1="W"))["type"] == "CONTINUATION")
check("CONTINUATION з відкатом H4 проти D1", TD.scenario_type(th(d1="W", h4="A"))["type"] == "CONTINUATION")
check("REVERSAL: D1 проти", TD.scenario_type(th(d1="A"))["type"] == "REVERSAL")
check("REVERSAL: H4 проти при D1 діапазоні", TD.scenario_type(th(h4="A"))["type"] == "REVERSAL")
check("RANGE: SHORT у discount — НЕ від правильної межі", TD.scenario_type(th(long_=False, zone4="discount"))["edge_ok"] is False)
rev = th(d1="A", h1="N", proof=False)
cr = TD.conflicts(rev, TD.scenario_type(rev))
check("REVERSAL: D1 проти очікувано, але без доказу H1 — warn", any(c["tf"] == "D1" and c["expected_for_type"] and c["severity"] == "warn" for c in cr))
cont = th(d1="W", h1="A", proof=True)
cc = TD.conflicts(cont, TD.scenario_type(cont))
check("CONTINUATION: H1 проти з доказом — info (відкат)", any(c["tf"] == "H1" and c["severity"] == "info" for c in cc))

# --- analyze: структура, режими
os.environ.pop("OFFICE2_LTF_MODE", None)
a = TD.analyze(dict(ada, entry_zone=ZONE, sl=SL), "LONG", T, lambda: m5, lambda: m1)
check("analyze: 6 етапів у порядку D1→H4→H1→M15→M5→M1", [s["tf"] for s in a["stages"]] == ["D1", "H4", "H1", "M15", "M5", "M1"])
check("analyze: M5 CONFIRMS, M1 CONFIRMS", a["stages"][4]["state"] == "CONFIRMS" and a["stages"][5]["state"] == "CONFIRMS")
check("analyze: режим за замовчуванням annotate", a["mode"] == "annotate")
os.environ["OFFICE2_LTF_MODE"] = "off"
check("режим off: M5/M1 не запитуються", TD.analyze(ada, "LONG", T, lambda: 1 / 0, lambda: 1 / 0)["ltf"]["status"] == "OFF")
os.environ["OFFICE2_LTF_MODE"] = "що_завгодно"
check("невідомий режим → annotate", TD.mode() == "annotate")
os.environ.pop("OFFICE2_LTF_MODE", None)
check("помилка завантаження M5 не ламає аналіз", TD.analyze(ada, "LONG", T, lambda: 1 / 0, lambda: 1 / 0)["ltf"]["status"] == "UNAVAILABLE")
check("рядок для Telegram містить тип", "діапазон" in (TD.summary_line(a) or ""))
print("OK" if not bad else f"FAIL {bad}")
sys.exit(1 if bad else 0)
