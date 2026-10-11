"""Офлайн-тести дослідження ліміту «3 стопи/добу»: симуляція кандидата, відтворення чинного ліміту, альтернативні правила, часова лінія блокування."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from office2.learning import gate_study as G

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if not cond else ""))
    if not cond:
        FAILS.append(name)


T0 = 1_800_000_000 - (1_800_000_000 % 86400) + 3600       # 01:00 UTC доби
def grid(price_path):
    """price_path: список (мінута_від_T0, o, h, l, c) → щільні 1m-бари."""
    bars = {}
    for m, o, h, l, c in price_path:
        bars[T0 + 60 * m] = (float(T0 + 60 * m), o, h, l, c)
    return [bars[k] for k in sorted(bars)]


def ev(i, minute, d="LONG", tp=(102.0, 104.0, 106.0), **kw):
    e = {"id": f"E{i}", "sym": "X", "dir": d, "decision_ts": T0 + 60 * minute, "entry": 100.0, "sl": 99.0, "tp": list(tp), "f": {}, "source": "BLOCKED", "tradable": True}
    e.update(kw)
    return e


def flat(m0, m1, p=100.0):
    return [(m, p, p + 0.1, p - 0.1, p) for m in range(m0, m1)]


# Часова лінія: перші 3 події — SL (ціна падає до 98.9), четверта (блокована) — TP1
bars = []
for m in range(0, 400):
    bars.append((m, 100.0, 100.1, 99.9, 100.0))
def setbar(m, o, h, l, c):
    bars[m] = (m, o, h, l, c)
for m in (11, 31, 51):                       # SL-свічки для подій 0,1,2 (кожна подія входить на наступній хвилині)
    setbar(m, 100.0, 100.1, 98.8, 99.0)
setbar(122, 100.0, 102.5, 99.9, 102.3)        # TP1 для події 3 (вхід ~101 хв)
b1 = grid(bars)
end = T0 + 60 * 400
e = [ev(0, 5), ev(1, 25), ev(2, 45), ev(3, 120, source="BLOCKED")]
e[0]["source"] = e[1]["source"] = e[2]["source"] = "DELIVERED"
sim = [G.simulate_event(x, b1, end) for x in e]
for x, s in zip(e, sim):
    x.update(s)
check("симуляція: 3 SL-first, 4-та TP1-first", [s["a_outcome"] for s in sim] == ["SL", "SL", "SL", "TP"], str([s["a_outcome"] for s in sim]))
check("SL-milestone зафіксований", all(s["sl_milestone_ts"] for s in sim[:3]) and sim[3]["sl_milestone_ts"] is None)
check("витрати відняті: SL < −$10", all(s["pnl_a"] < -10 for s in sim[:3]), str([s["pnl_a"] for s in sim[:3]]))

repl = G.run_rule("R_gate3_replica", e)
check("чинний ліміт відтворено: 3 прийняті, 4-та заблокована", repl["admitted"] == 3 and repl["sl_first"] == 3 and repl["pnl_a_usd"] < -30, str(repl))
nol = G.run_rule("R1_no_limit", e)
check("без ліміту: 4 прийняті, 1 TP", nol["admitted"] == 4 and nol["tp1_first"] == 1, str(nol))
check("різниця = результат відсіченої 4-ї", abs((nol["pnl_a_usd"] - repl["pnl_a_usd"]) - e[3]["pnl_a"]) < 0.02)
r4 = G.run_rule("R4_pause_2h_after_each_stop", e)
check("пауза 2 год після кожного стопу: подія 1,2 (<2 год) відсічені", r4["admitted"] == 1, str(r4))
r7 = G.run_rule("R7_after_3_stops_only_clean", e)
check("після 3 стопів лише «чисті» (≤1 ризик-ознаки): 4-та проходить", r7["admitted"] == 4, str(r7))
e[3]["f"] = {"counter_trend": True, "m5_trigger_no": True}
r7b = G.run_rule("R7_after_3_stops_only_clean", e)
check("4-та з 2 ризик-ознаками блокується", r7b["admitted"] == 3, str(r7b))

# стоп після TP1 не є A-збитком: R2 його не рахує
e2 = [dict(x) for x in e[:3]]
e2[0]["tp1_ts"] = e2[0]["sl_milestone_ts"] - 600            # TP1 був раніше SL → у R2 не рахується
extra = ev(9, 200, source="BLOCKED"); extra.update(G.simulate_event(extra, b1, end))
r2 = G.run_rule("R2_count_only_A_losses", e2 + [extra])
rg = G.run_rule("R_gate3_replica", e2 + [extra])
check("R2: стоп після TP1 не рахується → кандидат допущений; чинне правило — ні", r2["admitted"] == 4 and rg["admitted"] == 3, f"{r2['admitted']} {rg['admitted']}")

# денна межа кількості READY
many = [ev(100 + i, 300 + i, source="BLOCKED") for i in range(12)]
for x in many:
    x.update(G.simulate_event(x, b1, end))
check("денний ліміт 8 READY діє у всіх правилах", G.run_rule("R1_no_limit", many)["admitted"] == 8)

# часова лінія з milestones (реальна структура)
ms = [{"level": "SL", "sent": T0 + 100, "sid": "a"}, {"level": "TP1", "sent": T0 + 50, "sid": "b"}, {"level": "SL", "sent": T0 + 200, "sid": "b"}, {"level": "SL", "sent": T0 + 300, "sid": "c"}]
tl = G.gate_timeline(ms)[0]
check("лінія: ліміт досягнуто на 3-му SL, 3-й — після TP1, кінець о 00:00 UTC", tl["limit_reached_at"] == T0 + 300 and tl["lock_ends_at"] % 86400 == 0 and tl["after_tp1"] == 1 and tl["stops"] == 3 and tl["third_stop_after_tp1"] is False)

# таблиця ознак
ft = G.flag_table([dict(x, f={"mirror_for": True}) for x in e])
check("таблиця ознак: n<30 позначено INSUFFICIENT", ft["Герчик: є дзеркальний рівень"]["status"].startswith("INSUFFICIENT"))
check("bootstrap CI лише при n≥10", G.bootstrap_mean_ci([1.0] * 5) is None and G.bootstrap_mean_ci([1.0, -1.0] * 10) is not None)

# фікстури читаються
fx = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "learning")
evs = G.load_events(os.path.join(fx, "gate_blocked_2026-10.json"), os.path.join(fx, "gate_delivered_2026-10.json"))
check("фікстури: 82 відсічені + доставлені", sum(1 for x in evs if x["source"] == "BLOCKED") == 82 and any(x["source"] == "DELIVERED" for x in evs))
mil = json.load(open(os.path.join(fx, "gate_milestones_2026-10.json")))["rows"]
tls = G.gate_timeline(mil)
check("реальна лінія: 11.10 ліміт досягнуто о 03:20:58Z", any(t["limit_reached_at"] and abs(t["limit_reached_at"] - 1791688858.03) < 1 for t in tls))

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
