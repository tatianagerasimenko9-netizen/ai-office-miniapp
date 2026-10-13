#!/usr/bin/env python3
"""AI Office: покрокова перевірка сценарію (daria_steps), нова Telegram-картка, скасування закриттям M15 ДО входу (INVALIDATED) і розділення скасування та захисного SL."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if not cond else ""))
    if not cond:
        FAILS.append(name)


from office2 import daria_steps as DS  # noqa: E402
from office2 import delivery as DL  # noqa: E402
import office_signal_track as T  # noqa: E402
from office_user_messages import scenario_event  # noqa: E402

snap = json.loads((ROOT / "scripts" / "fixtures" / "o2_snapshot_ada_2026-10-12.json").read_text(encoding="utf-8"))   # реальний READY ADA 12.10 11:30 UTC (Binance Futures)
VU = 1791804600 + 6 * 3600
d = DS.build(snap, VU)
ids = [s["id"] for s in d["steps"]]
check("порядок кроків зверху вниз: D1/H4 → H1 → M15 → M5 → M1 → супровід", ids == ["HTF", "H1", "M15", "M5", "M1", "FOLLOW"], str(ids))
by = {s["id"]: s for s in d["steps"]}
check("D1/H4 у реальному READY ADA — діапазон: НЕ підтверджує (не вигадуємо підтвердження)", by["HTF"]["status"] == "NEUTRAL")
check("H1 проти напрямку показано як ПРОТИ, а не сховано", by["H1"]["status"] == "AGAINST" and any("немає доказу повернення" in x for x in by["H1"]["refutes"]))
check("M15: підтверджено закриттям бару з точним часом", by["M15"]["status"] == "CONFIRMED" and by["M15"]["condition"]["type"] == "CLOSE" and by["M15"]["condition"]["closed_ts"] == snap["decided_ts"])
check("M5/M1 не є умовами READY: джерелом не задані", by["M5"]["status"] == "NOT_REQUIRED_BY_SOURCE" and by["M1"]["status"] == "NOT_REQUIRED_BY_SOURCE" and "X-NOT-SPECIFIED-DARIA-LTF-ENTRY-TP" in by["M1"]["sources"])
check("кожен крок має джерела й що НЕ ПІДТВЕРДЖЕНО", all(s["sources"] and s["unknown"] for s in d["steps"]))
check("скасування = ЗАКРИТТЯ M15 (ціна, ТФ), захисний SL = ДОТИК — окремі об'єкти", d["cancel"]["type"] == "CLOSE" and d["cancel"]["tf"] == "M15" and d["protective_sl"]["type"] == "TOUCH" and d["cancel"]["price"] != d["protective_sl"]["price"])
check("тексти не обіцяють, що очікування закриття захистить від вибивання", "не захищає" in d["protective_sl"]["text"])
check("TP2/TP3 присутні — пропусків не вигадано; відсутні цілі пояснюються", by["FOLLOW"]["gaps"] == [])
th2 = dict(snap["thesis"], targets=snap["thesis"]["targets"][:1])
d2 = DS.build(dict(snap, thesis=th2), VU)
check("якщо TP2/TP3 об'єктивно немає — пояснення замість вигаданих цілей", d2["steps"][-1]["gaps"] and "не вигадуємо" in d2["steps"][-1]["gaps"][0])
check("чому НЕ входити: ПРОТИ/ризики перелічені", any(x["type"] == "RISK" for x in d["not_now"]) and any(x["type"] == "AGAINST" for x in d["not_now"]))
# ціна втекла → не наздоганяти
r_away = DS.entry_state(snap["thesis"], 0.2530)
check("ціна втекла далі 0.6 R від тригера → RAN_AWAY (чекати ретест, не переслідувати)", r_away["state"] == "RAN_AWAY" and "не наздоганяти" in r_away["text"])
check("ціна в зоні → IN_ZONE", DS.entry_state(snap["thesis"], 0.2510)["state"] == "IN_ZONE")
check("ціна за SL → SL_ZONE", DS.entry_state(snap["thesis"], 0.2490)["state"] == "SL_ZONE")
check("SHORT дзеркально", DS.entry_state({"dir": "SHORT", "entry": 100.0, "sl": 101.0, "trigger_level": 100.0, "entry_zone": [99.8, 100.0], "invalidation": {"price": 100.5}}, 98.5)["state"] == "RAN_AWAY")

# Telegram-картка
snap2 = dict(snap, valid_until_ts=VU)
cap = DL.build_caption(snap2, snap["decided_ts"] + 100)
check("картка: AI Office · №, 🟢 ADA · LONG · READY · #ADAUSDT", cap.startswith("AI Office") and "🟢 ADA · LONG · READY · #ADAUSDT" in cap, cap[:80])
check("картка: вхід, SL, TP1–TP3, скасування закриттям M15, підтвердження, строк у Київ", all(x in cap for x in ("ВХІД", "🔴 SL", "TP1", "TP2", "TP3", "Скасування: закриття M15 нижче", "(Київ)")))
# Підтвердження D1/H4/H1 — у Mini App (компактний підпис #242).
check("картка без довгого «Чому» і без OFFICE2/LIVE BETA", "Чому:" not in cap and "OFFICE2" not in cap and "LIVE BETA" not in cap)
check("картка: R/R до TP1 показано", "R/R до TP1" in cap)

# --- скасування закриттям M15 до входу (simulate)
T0 = 1_800_000_000.0 - (1_800_000_000.0 % 900)


def m1(t, o, h, l, c):
    return {"ts": t, "open": o, "high": h, "low": l, "close": c, "src": "binance_futures"}


def m1_bucket(base, closes, price_hi, price_lo):
    return [m1(base + 60 * i, closes[i], price_hi, price_lo, closes[i]) for i in range(15)]


plan = {"scenario_id": "S", "symbol": "XUSDT", "direction": "LONG", "entry": 100.0, "sl": 98.0, "tp1": 103.0, "tp2": 105.0, "tp3": 107.0, "confirmed_ts": T0, "valid_until_ts": T0 + 6 * 3600, "inval_px": 99.0}
now = T0 + 2 * 900 + 30        # обидва M15-бари закрито
# ціна над входом (101), потім M15 закривається нижче 99 (98.5), вхід (100) не торкнуто → INVALIDATED о закритті бару
bars = m1_bucket(T0, [101.0] * 15, 101.5, 100.5) + m1_bucket(T0 + 900, [98.5] * 15, 101.0, 98.4)
res = T.simulate(plan, bars, now, tf_sec=60.0, live_tail=True)
# у барі 2 ціна проходила 101→98.4 (low<100 торкає вхід 100) — перший бар без входу, в другому вхід торкнуто ДО закриття: це вхід, не скасування
check("вхід торкнуто всередині бару до його закриття → вхід був ДО скасування (звичайний супровід)", res["status"] in ("STOP", "PENDING") and res["filled_at"] is not None, str(res))
bars_b = m1_bucket(T0, [101.0] * 15, 101.5, 100.5) + m1_bucket(T0 + 900, [99.5] * 14 + [98.5], 100.9, 98.4)
for b in bars_b[15:]:
    b["high"] = 100.9      # ціна не торкається входу 100 (макс 100.9 > 100 торкає!) — тому робимо максимум нижче входу
    b["high"] = 99.9
res_b = T.simulate(plan, bars_b[:15] + [dict(b, high=min(b["high"], 99.9)) for b in bars_b[15:]], now, tf_sec=60.0, live_tail=True)
# перший бар [T0..T0+900): high 101.5 ≥ 100 і low 100.5 > 100 → вхід 100 не торкнуто (lo<=e<=hi: low 100.5 > 100 → ні)
check("M15 закрилась нижче рівня скасування до входу → INVALIDATED, без TP/PnL", res_b["status"] == "INVALIDATED" and res_b["filled_at"] is None and not res_b["reached"], str(res_b))
check("INVALIDATED є подією життя сценарію з ціною скасування", T._levels_of(res_b) == ["INVALIDATED"])
# прокол тінню без закриття нижче → не скасування
bars_w = m1_bucket(T0, [101.0] * 15, 101.5, 100.5) + [dict(x, low=98.4, close=99.6) for x in m1_bucket(T0 + 900, [99.6] * 15, 99.9, 98.4)]
res_w = T.simulate(plan, bars_w, now, tf_sec=60.0, live_tail=True)
check("прокол тінню нижче рівня без закриття M15 нижче — НЕ скасування", res_w["status"] != "INVALIDATED", str(res_w))
# не зібраний повністю M15 → скасування не оголошується
bars_p = m1_bucket(T0, [101.0] * 15, 101.5, 100.5) + [dict(x, high=99.9, close=98.5) for x in m1_bucket(T0 + 900, [98.5] * 15, 99.9, 98.4)][:10]
res_p = T.simulate(plan, bars_p, T0 + 900 + 10 * 60, tf_sec=60.0, live_tail=True)
check("незакрита M15 скасування не оголошує", res_p["status"] != "INVALIDATED", str(res_p))
# плани без inval_px (старі) не змінюються
plan_old = {k: v for k, v in plan.items() if k != "inval_px"}
check("старий план без inval_px поводиться як раніше", T.simulate(plan_old, bars_b, now, tf_sec=60.0, live_tail=True)["status"] != "INVALIDATED")
# SHORT дзеркально
plan_s = dict(plan, direction="SHORT", entry=100.0, sl=102.0, tp1=97.0, tp2=95.0, tp3=93.0, inval_px=101.0)
bars_s = [dict(x, low=100.1, high=min(x["high"], 100.5)) for x in m1_bucket(T0, [99.0] * 15, 99.5, 99.0)] + [dict(x, high=100.0 - 0.1, close=101.5, low=99.5) for x in m1_bucket(T0 + 900, [101.5] * 15, 99.9, 99.5)]
res_s = T.simulate(plan_s, bars_s, now, tf_sec=60.0, live_tail=True)
check("SHORT: закриття M15 вище рівня скасування до входу → INVALIDATED", res_s["status"] == "INVALIDATED", str(res_s))
txt = scenario_event(symbol="XUSDT", direction="LONG", level="INVALIDATED", price=99.0)
check("Telegram-подія INVALIDATED: скасовано, входити не треба; не СТОП", "СЦЕНАРІЙ СКАСОВАНО" in txt and "СТОП" not in txt and "ще до входу" in txt)
import office_alert_gate as AG  # noqa: E402

check("текст INVALIDATED проходить Telegram-шлюз (не наказує вхід/ордер)", not AG.text_grants_entry(txt) and not AG.text_instructs_position_change(txt))

# --- наскрізно: SIGNAL_PLAN → pending_milestones → INVALIDATED (не silent, з ціною скасування) → одноразово
import tempfile  # noqa: E402
import office_bridge as OB  # noqa: E402

db = os.path.join(tempfile.mkdtemp(), "e2e.db")
OB.init_office_db(db)
T.log_event if hasattr(T, "log_event") else None
OB.log_event(db, T.EV_MILESTONE_ON, {"since": 0.0}, "")
tc = (time.time() // 900) * 900 - 3 * 900          # план підтверджено 3 бари тому
T.record_plan(db, scenario_id="O2|e2e|1", symbol="XUSDT", direction="LONG", tf="M15", entry=100.0, sl=98.0, tp1=103.0, tp2=105.0, tp3=107.0, confirmed_ts=tc, valid_until_ts=tc + 6 * 3600,
              confirm_msg_id=777, inval_px=99.0)
bars_e = []
for k in range(2):                                   # два закритих M15: вище входу, потім закриття нижче 99 без торкання входу (high < 100)
    base = tc + k * 900
    px = 101.0 if k == 0 else 98.8
    hi = 101.5 if k == 0 else 99.9
    lo = 100.6 if k == 0 else 98.5
    bars_e += [{"ts": datetime.fromtimestamp(base + 60 * i, tz=timezone.utc).isoformat(), "open": px, "high": hi, "low": lo, "close": px, "src": "binance_futures"} for i in range(15)]
ms = T.pending_milestones(db, lambda sym, tf, n: bars_e, time.time(), "all")
lv = [m["level"] for m in ms]
check("pending_milestones: подія INVALIDATED, не тиха, ціна скасування, без ENTRY/TP", lv == ["INVALIDATED"] and not ms[0]["silent"] and ms[0]["price"] == 99.0 and ms[0]["src"] == "binance_futures", str(ms))
T.record_milestone(db, ms[0], 4242)
check("повторний прохід не дублює INVALIDATED", T.pending_milestones(db, lambda sym, tf, n: bars_e, time.time(), "all") == [])
res_t = T.tick(db, lambda sym, tf, n: bars_e, time.time())
check("SIGNAL_RESULT: outcome INVALIDATED, filled=False", res_t and res_t[0]["outcome"] == "INVALIDATED" and res_t[0]["filled"] is False, str(res_t))

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
