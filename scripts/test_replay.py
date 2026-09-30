"""Replay контрольних кейсів: ядро на синтетичних «реальних» свічках, шлюз плану (LSK відхиляється), чесні статуси NO_DATA/NOT_FILLED, вердикт."""
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

import office_replay as rp  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


T0 = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)


def bars(n, step_sec, price_fn):
    out = []
    for i in range(n):
        c = price_fn(i)
        o = price_fn(i - 1)
        out.append({"ts": (T0 + timedelta(seconds=step_sec * i)).isoformat(), "open": o, "high": max(o, c) * 1.002, "low": min(o, c) * 0.998, "close": c, "volume": 100.0})
    return out


def path(i):   # 100 → 112 плавно, далі відкат
    if i < 100:
        return 100.0 + 0.01 * math.sin(i)
    if i < 260:
        return 100.0 + (i - 100) * 0.075
    return 112.0 - (i - 260) * 0.05


def fetch(sym, tf, n):
    sec = rp.TF_SEC[tf]
    per = {900: 1, 3600: 4, 14400: 16}[sec]
    return bars(max(40, 330 // per + 10), sec, lambda i: path(i * per))


case = {"symbol": "TESTUSDT", "side": "LONG", "entry": 100.0, "sl": 97.0, "tp1": 104.0, "tp2": 108.0, "start": "2026-09-29T01:00:00Z"}
data = rp.load_data("TESTUSDT", fetch)
res = rp.replay(case, data)
check("вхід заповнено, є хронологія", res["status"] == "FILLED" and len(res["timeline"]) >= 1, str(res)[:300])
codes = [x["code"] for x in res["timeline"]]
check("жодна порада не повторилась", len(codes) == len(set(codes)), str(codes))
check("є порада по TP1", any(c.startswith("TP1") for c in codes), str(codes))
check("MFE додатний, MAE не від'ємний", res["mfe_pct"] > 0 and res["mae_pct"] >= 0)

nf = rp.replay({**case, "entry": 50.0, "sl": 48.0, "tp1": 55.0}, data)
check("ціна не торкнулась входу → NOT_FILLED (а не вигадана угода)", nf["status"] == "NOT_FILLED")
nd = rp.replay(case, {"15m": []})
check("немає свічок → NO_DATA, нічого не вигадано", nd["status"] == "NO_DATA" and nd["ok"] is False)

# шлюз плану: LSK (RR≈1,40 після комісій) відхилено, хороший план проходить
lsk_gate = rp.plan_gate(rp.CASES["LSK"])
check("LSK: новий шлюз відхиляє план (RR після комісій < 1,5)", bool(lsk_gate) and "1,4" in lsk_gate, str(lsk_gate))
good = {"symbol": "BTCUSDT", "side": "LONG", "entry": 100.0, "sl": 98.0, "tp1": 104.0}
check("план із RR=2 шлюз пропускає", rp.plan_gate(good) is None, str(rp.plan_gate(good)))

# вердикт
v = rp.verdict("AKE", res, None)
check("вердикт ПРОЙДЕНО для чистої хронології", v["passed"], str(v))
bad = {"ok": True, "status": "FILLED", "timeline": [{"code": "TP1", "text": "Угоду закрито."}, {"code": "TP1", "text": "x"}]}
vb = rp.verdict("AKE", bad, None)
check("вердикт НЕ пройдено: «закрито» без підтвердження і дубль поради", not vb["passed"] and sum(1 for c in vb["checks"] if not c["ok"]) == 2, str(vb))
check("вердикт LSK вимагає відхилення плану", rp.verdict("LSK", res, None)["passed"] is False and rp.verdict("LSK", res, "відхилено")["passed"] is True)

# повний прогін кейсів на підставних свічках + звіт
out = rp.run_all(["AKE", "LSK"], fetch=fetch, printer=lambda s: None)
check("run_all повертає результат по кожному кейсу", [r["case"] for r in out] == ["AKE", "LSK"])
check("кейси мають реальні параметри з журналу", all(rp.CASES[k]["entry"] > 0 and rp.CASES[k]["sl"] > 0 for k in rp.CASES) and "LONGXIA" in rp.CASES and rp.CASES["LONGXIA"]["symbol"] == "龙虾USDT")
lines = rp.format_report(out[1])
check("звіт містить вердикт і шлюз", any("вердикт LSK" in x for x in lines) and any("шлюз плану" in x for x in lines))

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
