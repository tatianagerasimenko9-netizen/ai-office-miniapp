#!/usr/bin/env python3
"""ICT SMC HUNTER і PUMP & DUMP HUNTER не впливають на рішення Лева (до доведення відповідності Pine).
Регресійний канал і решта аналітики працюють; відключення не блокує готові сигнали й не змінює інші підтвердження."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
os.environ.pop("OFFICE_PINE_INFLUENCE", None)

import office_ict_hunter as hunter  # noqa: E402
import office_indicator_gate as gate  # noqa: E402
import office_lev_verdict as lv  # noqa: E402
import office_pump_dump as pdump  # noqa: E402
from office_lev_verdict import (  # noqa: E402
    ACTION_SEND,
    ACTION_WAIT,
    STANCE_NOT_CONNECTED,
    collect_indicator_stances,
    draft_lev_scenario,
    finalize_lev,
    indicator_stance,
)

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def cand(tag, lo, hi, tf="H1", label=""):
    return {"tag": tag, "lo": float(lo), "hi": float(hi), "tf": tf, "label": label or tag}


def c(o, h, l, cl, vol=12.0):
    return {"open": o, "high": h, "low": l, "close": cl, "volume": vol}


LONG_CANDS = [cand("sc_ote", 83200, 83800, "M15", "сильна свічка M15"), cand("ob", 83150, 83750, "H1", "OB H1"),
              cand("fib_h4", 83000, 83900, "H4", "Фібо 0.618–0.786 H4"), cand("breaker", 83300, 83650, "H1", "breaker H1")]
draft = draft_lev_scenario(symbol="BTCUSDT", timeframe="H1", price=84870.0, atr_h1=900.0, day_used_pct=40.0,
                           candidates_long=LONG_CANDS, candidates_short=[cand("ob", 85100, 85600, "H1", "OB H1")],
                           market_context={"data_status": "PARTIAL", "btc": "спот 84870"})
check("база: власний сетап Лева LONG готовий", draft.get("direction") == "LONG" and draft.get("send_card"), str(draft.get("reason")))


def st(direction, signal=True, connected=True):
    return indicator_stance(lev_direction="LONG", connected=connected, signal=signal, indicator_direction=direction, reason="тест")


def stances(pump="SHORT", hunt="SHORT", chan=None):
    return {
        "pump_dump": st(pump) if pump else st("", signal=False),
        "ict_hunter": st(hunt) if hunt else st("", signal=False),
        "channel": st(chan) if chan else st("", signal=False, connected=False),
        "pine_alerts": {"stance": STANCE_NOT_CONNECTED, "connected": False, "creates_enter": False},
    }


# 1. Вимкнено: суперечність двох портів НЕ блокує готовий сигнал
base = finalize_lev(draft, stances(pump=None, hunt=None))
both_against = finalize_lev(draft, stances(pump="SHORT", hunt="SHORT"))
check("обидва порти «проти» → сигнал не блокується (SEND)", both_against["action"] == ACTION_SEND and both_against["send"], both_against["reason"])
check("рішення те саме, що без індикаторів: напрям/вхід/стоп/TP/збіги",
      all(both_against[k] == base[k] for k in ("action", "direction", "entry", "sl", "tp1", "confluence", "db_status")))
both_for = finalize_lev(draft, stances(pump="LONG", hunt="LONG"))
check("обидва порти «за» → нічого не додають: той самий SEND і та сама причина", both_for["action"] == ACTION_SEND and both_for["reason"] == base["reason"])
check("текст висновку не каже, що індикатори підсилили", "підсилюють" not in both_for["lev_note"], both_for["lev_note"])

# 2. Канал (залишено в аналітиці) і далі впливає як раніше
chan_against = finalize_lev(draft, stances(pump=None, hunt=None, chan="SHORT"))
check("регресійний канал «проти» → як і раніше WAIT", chan_against["action"] == ACTION_WAIT)
chan_for = finalize_lev(draft, stances(pump="SHORT", hunt="SHORT", chan="LONG"))
check("канал «за» + порти «проти» → SEND (порти не впливають)", chan_for["action"] == ACTION_SEND)

# 3. Інші вето не зачеплені
atr = dict(draft)
atr["atr"] = {"gerchik_entry_blocked": True, "t0_entry_blocked": False, "label": "ATR day_used 91%"}
check("ATR-вето працює як раніше", finalize_lev(atr, stances())["action"] == "SKIP")
rr = dict(draft)
rr["rr"] = 1.2
check("RR-фільтр працює як раніше", finalize_lev(rr, stances())["action"] == "SKIP")
liq = dict(draft)
liq["liquidity"] = {"in_pool": True, "reason": "ліквідність біля стопа"}
check("вето ліквідності працює як раніше", finalize_lev(liq, stances())["action"] == ACTION_WAIT)
empty = dict(draft)
empty["send_card"] = False
check("без власного сетапу Лева порти не створюють ENTER", finalize_lev(empty, stances(pump="LONG", hunt="LONG"), hunter_only_enter=True)["action"] != ACTION_SEND)

# 4. collect: порти не рахуються, канал рахується
calls = {"n": 0}
_orig = (lv.evaluate_ict_hunter, lv.evaluate_pump_dump)
lv.evaluate_ict_hunter = lambda **k: calls.__setitem__("n", calls["n"] + 1) or {}
lv.evaluate_pump_dump = lambda **k: calls.__setitem__("n", calls["n"] + 1) or {}
h1 = [c(100 + i * 0.1, 101 + i * 0.1, 99 + i * 0.1, 100.5 + i * 0.1) for i in range(120)]
got = collect_indicator_stances(lev_direction="LONG", price=112.0, candles_m15=h1, candles_h1=h1, candles_d1=h1[:10])
lv.evaluate_ict_hunter, lv.evaluate_pump_dump = _orig
check("Hunter і Pump НЕ обчислюються", calls["n"] == 0)
check("їхні позиції: NOT_CONNECTED, disabled, не підтверджують і не суперечать",
      all(got[k]["stance"] == STANCE_NOT_CONNECTED and got[k].get("disabled") and not got[k]["signal"] and not got[k]["creates_enter"] for k in ("pump_dump", "ict_hunter")))
check("канал обчислюється (підключений)", got["channel"]["connected"] is True and got["raw"]["channel"].get("ok") is True)

# 5. Повний цикл Лева із вимкненими портами формує готовий сигнал
cyc = lv.lev_cycle(symbol="BTCUSDT", price=84870.0, timeframe="H1", candles_m15=h1, candles_h1=h1, atr_h1=900.0, day_used_pct=40.0,
                   candidates_long=LONG_CANDS, candidates_short=[cand("ob", 85100, 85600, "H1", "OB H1")],
                   market_context={"data_status": "PARTIAL", "btc": "спот 84870"})
check("lev_cycle: готовий сигнал формується (SEND)", cyc["action"] == ACTION_SEND, cyc["reason"])

# 6. Радар не додає hunter_score; супровід Pump не працює
from datetime import datetime, timezone  # noqa: E402
import office_radar as radar  # noqa: E402

calls2 = {"n": 0}
_orig_r = hunter.evaluate_ict_hunter
hunter.evaluate_ict_hunter = lambda **k: calls2.__setitem__("n", calls2["n"] + 1) or {"ok": True, "score": 9, "patterns": ["SMS"]}
daily_ok = []
for _ in range(8):
    daily_ok += [c(100, 110, 90, 100), c(100, 111, 89.5, 101)]
res = radar.evaluate_radar(symbol="BTCUSDT", price=10.0, daily_candles=daily_ok,
                           sweep_candles=[c(10, 10.2, 9.8, 10.0), c(10, 10.3, 9.85, 10.1), c(10.0, 10.1, 9.5, 9.95)],
                           m15_candles=[c(9.9, 10.2, 9.9, 10.2)], day_used_pct=40.0, in_kill_zone=True,
                           utc_now=datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc))
hunter.evaluate_ict_hunter = _orig_r
check("радар: сигнал формується, Hunter не викликається, hunter_score у картці нема",
      res.status == "SIGNAL" and calls2["n"] == 0 and "hunter_score" not in (res.card or {}), f"{res.status} {calls2} {list((res.card or {}).keys())}")

# 7. Повернення впливу (rollback): OFFICE_PINE_INFLUENCE=1 → поведінка до вимкнення
os.environ["OFFICE_PINE_INFLUENCE"] = "1"
check("rollback: вплив повернено змінною", gate.pine_influence_enabled() and gate.is_active("ict_hunter") and gate.is_active("pump_dump"))
check("rollback: суперечність Hunter знову дає WAIT", finalize_lev(draft, stances(pump=None, hunt="SHORT"))["action"] == ACTION_WAIT)
os.environ.pop("OFFICE_PINE_INFLUENCE")
check("вимкнено за замовчуванням", not gate.pine_influence_enabled() and not gate.is_active("ict_hunter") and gate.is_active("channel"))
check("код портів і parity лишились", callable(hunter.evaluate_ict_hunter) and callable(pdump.evaluate_pump_dump))

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
