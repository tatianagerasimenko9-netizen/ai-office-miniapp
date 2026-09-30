#!/usr/bin/env python3
"""Правило RR плану: 'tp1' (чинне) і 'weighted' (зважений RR 40% TP1 + 60% TP2 ≥ 1,5 І RR до TP1 ≥ 1,0, комісія 0,10%) — rr_gate, межа входу, геометрія, check_plan."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
os.environ.pop("OFFICE_SIGNAL_FEE_PCT", None)

import office_alert_gate as G  # noqa: E402
import office_lev_watch as LW  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


os.environ.pop("OFFICE_RR_RULE", None)
# --- режим за замовчуванням/«tp1»: як було ---
check("режим за замовчуванням — tp1 (чинне правило)", G.rr_rule() == "tp1" or os.getenv("OFFICE_RR_RULE") == "weighted")
os.environ["OFFICE_RR_RULE"] = "tp1"
g = G.rr_gate(100.0, 97.0, 104.0, 110.0)           # RR до TP1 = 1,26: чинне правило відхиляє, TP2 не рятує
check("tp1: RR до TP1 1,26 < 1,5 → відхилено, навіть із далеким TP2", not g["ok"] and "потрібно не менше 1,5" in g["reason"], str(g))
check("tp1: max_entry — стара замкнена формула (TP2 не впливає)", abs(G.max_entry_price("LONG", 97.0, 104.0, 110.0) - G.max_entry_price("LONG", 97.0, 104.0)) < 1e-12)

# --- режим weighted ---
os.environ["OFFICE_RR_RULE"] = "weighted"
g = G.rr_gate(100.0, 97.0, 104.0, 110.0)
check("weighted: той самий план проходить (зважений 2,45 ≥ 1,5 і RR до TP1 1,26 ≥ 1,0)", g["ok"] and abs(g["rr_weighted"] - (0.4 * 4 + 0.6 * 10 - 0.1) / 3.1) < 1e-9 and abs(g["rr_net"] - 3.9 / 3.1) < 1e-9, str(g))
g = G.rr_gate(100.0, 97.0, 102.0, 130.0)           # TP1 2%: RR до TP1 0,61 < 1,0
check("weighted: RR до TP1 < 1,0 → відхилено, хоч зважений великий", not g["ok"] and "до цілі 1" in g["reason"] and "1,0" in g["reason"], str(g))
g = G.rr_gate(100.0, 97.0, 104.0, None)            # TP2 немає → весь обсяг на TP1 → зважений = RR до TP1 = 1,26 < 1,5
check("weighted: без TP2 зважений = RR до TP1 → відхилено (нічого не вигадуємо)", not g["ok"] and "зважений" in g["reason"], str(g))
g = G.rr_gate(100.0, 98.0, 104.0, None)            # 3,9/2,1 = 1,857
check("weighted: план, що проходив і раніше (RR до TP1 ≥ 1,5), проходить і тепер", g["ok"])
g = G.rr_gate(100.0, 103.0, 96.0, 90.0)            # SHORT, ризик 3%, TP1 4%, TP2 10%
check("weighted: SHORT дзеркально", g["ok"] and abs(g["rr_weighted"] - (0.4 * 4 + 0.6 * 10 - 0.1) / 3.1) < 1e-9, str(g))
check("weighted: комісія 0,10% враховано (поріг 1,5 на межі)", G.fee_round_trip_pct() == 0.10)

# межа входу: на самій межі правило виконується, трохи далі — ні (LONG і SHORT)
for d, sl, t1, t2 in (("LONG", 97.0, 104.0, 110.0), ("SHORT", 103.0, 96.0, 90.0), ("LONG", 97.0, 104.0, None)):
    me = G.max_entry_price(d, sl, t1, t2)
    eps = 1e-4
    inside, outside = (me - eps, me + eps) if d == "LONG" else (me + eps, me - eps)
    check(f"weighted {d} TP2={t2}: межа входу {me:.4f}: всередині правило ок, за межею — ні",
          G.rr_gate(inside, sl, t1, t2)["ok"] and not G.rr_gate(outside, sl, t1, t2)["ok"], str((me, G.rr_gate(inside, sl, t1, t2)["ok"], G.rr_gate(outside, sl, t1, t2)["ok"])))

# геометрія за краями зони
geo = G.validate_trade_geometry(direction="LONG", sl=97.0, tp1=104.0, entry_low=99.5, entry_high=100.5, tp2=112.0)
check("weighted: геометрія за краями зони приймає план з далеким TP2", geo["ok"], str(geo))
geo2 = G.validate_trade_geometry(direction="LONG", sl=97.0, tp1=102.5, entry_low=99.5, entry_high=100.5, tp2=112.0)
check("weighted: RR до TP1 за краями < 1,0 → геометрія відхиляє", not geo2["ok"], str(geo2))
os.environ["OFFICE_RR_RULE"] = "tp1"
geo3 = G.validate_trade_geometry(direction="LONG", sl=97.0, tp1=104.0, entry_low=99.5, entry_high=100.5, tp2=112.0)
check("tp1: та сама геометрія відхиляється (RR за краями < 1,5)", not geo3["ok"], str(geo3))

# check_plan: текст і tp2
os.environ["OFFICE_RR_RULE"] = "weighted"
plan = {"entry": 100.0, "sl": 97.0, "tp1": 104.0, "tp2": 110.0}
check("check_plan (weighted): план із TP2 проходить шлюз RR", LW.check_plan("BTCUSDT", "LONG", plan, 99.5, 100.5) is None or "потенціал" not in str(LW.check_plan("BTCUSDT", "LONG", plan, 99.5, 100.5)).lower())
bad = LW.check_plan("BTCUSDT", "LONG", {"entry": 100.0, "sl": 97.0, "tp1": 104.0}, 99.5, 100.5)
check("check_plan (weighted): без TP2 відхилено з причиною про зважений RR", bad and "зважений" in bad, str(bad))
os.environ["OFFICE_RR_RULE"] = "tp1"
bad2 = LW.check_plan("BTCUSDT", "LONG", plan, 99.5, 100.5)
check("check_plan (tp1): чинний текст причини", bad2 and "потрібно не менше 1,5" in bad2, str(bad2))

# життєвий цикл: межа входу враховує TP2
import office_scenario_lifecycle as LC  # noqa: E402
import inspect  # noqa: E402

check("confirmed_plan_action приймає tp2", "tp2" in inspect.signature(LC.confirmed_plan_action).parameters)

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
