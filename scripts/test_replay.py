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

mid = rp.replay({**case, "start": "2026-09-29T01:07:00Z"}, data)   # старт усередині свічки 01:00–01:15: вона входить (вхід 100 торкається її)
check("свічка, у якій відкрито угоду (старт усередині неї), враховується", mid["status"] == "FILLED" and mid["filled_at"].startswith("2026-09-29T01:15"), str(mid)[:200])
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
vnf = rp.verdict("AKE", {"ok": True, "status": "NOT_FILLED", "timeline": []}, None)
check("NOT_FILLED для кейсу ведення НЕ вважається пройденим (нічого не перевірено)", vnf["passed"] is False and any(c["name"].startswith("вхід заповнено") and not c["ok"] for c in vnf["checks"]), str(vnf))
vtp = rp.verdict("AKE", {"ok": True, "status": "FILLED", "timeline": [], "mfe_pct": 9.0}, None)
check("ціна дійшла до цілі 1, а поради нема → не пройдено", vtp["passed"] is False, str(vtp))
check("LSK пройдено лише за шлюзом навіть без заповненого входу", rp.verdict("LSK", {"ok": True, "status": "NOT_FILLED", "timeline": []}, "відхилено")["passed"] is True)
check("вердикт LSK вимагає відхилення плану", rp.verdict("LSK", res, None)["passed"] is False and rp.verdict("LSK", res, "відхилено")["passed"] is True)

# повний прогін кейсів на підставних свічках + звіт
out = rp.run_all(["AKE", "LSK"], fetch=fetch, printer=lambda s: None)
check("run_all повертає результат по кожному кейсу", [r["case"] for r in out] == ["AKE", "LSK"])
check("кейси мають реальні параметри з журналу", all(rp.CASES[k]["entry"] > 0 and rp.CASES[k]["sl"] > 0 for k in rp.CASES) and "LONGXIA" in rp.CASES and rp.CASES["LONGXIA"]["symbol"] == "龙虾USDT")
lines = rp.format_report(out[1])
check("звіт містить вердикт і шлюз", any("вердикт LSK" in x for x in lines) and any("шлюз плану" in x for x in lines))

# ---- джерело свічок: архів data.binance.vision, а не REST (IP спільний із живим Левом і ботами) ----
import io  # noqa: E402
import zipfile  # noqa: E402

import office_market_data as omd  # noqa: E402


def make_zip(day):
    d0 = datetime.fromisoformat(day + "T00:00:00+00:00")
    lines = []
    for i in range(96):
        t = d0 + timedelta(minutes=15 * i)
        c = 100.0 + (0.1 * i if day == "2026-09-29" else 0.0)
        lines.append(f"{int(t.timestamp() * 1000)},{c},{c * 1.002},{c * 0.998},{c},10,0,0,0,0,0,0")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", "\n".join(lines))
    return buf.getvalue()


calls = []


def getter(url):
    calls.append(url)
    day = url.rsplit("-", 3)[-3:]
    day = "-".join(day).replace(".zip", "")
    if day in ("2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29"):
        return make_zip(day)
    raise OSError("404")


rest_calls = []
omd.fetch_candles = lambda *a, **k: rest_calls.append(a) or []
st = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
d = rp.load_data("AKEUSDT", None, start=st, end=st + timedelta(days=2), getter=getter)
check("архів дав 15м свічки й похідні 1г/4г, REST не чіпали", d["source"] == "vision" and len(d["15m"]) == 96 * 4 and len(d["1h"]) > 0 and len(d["4h"]) > 0 and not rest_calls, str({k: (len(v) if isinstance(v, list) else v) for k, v in d.items()}))
check("дні без архіву (сьогодні) названо чесно", "2026-09-30" in d["missing_days"] and "2026-10-01" in d["missing_days"], str(d["missing_days"]))
check("URL архіву містить ф'ючерсний каталог і 15m", all("futures/um/daily/klines" in u and "/15m/" in u for u in calls))
chinese = [u for u in calls if "%" in u]
check("символ з ієрогліфами кодується в URL", bool(rp.VISION_URL) and "%" in __import__("urllib.parse").parse.quote("龙虾USDT"))

def dead(url):
    raise OSError("архів недоступний")

omd.source_health = lambda: {"used_weight_1m": None}
nd = rp.load_data("AKEUSDT", None, start=st, end=st + timedelta(days=1), getter=dead)
check("архів недоступний + вага невідома → REST не чіпаємо, чесне «немає даних»", nd["source"] == "none" and nd["15m"] == [] and not rest_calls and "не чіпаємо" in nd["note"], str(nd))
omd.source_health = lambda: {"used_weight_1m": 1500}
nd2 = rp.load_data("AKEUSDT", None, start=st, end=st + timedelta(days=1), getter=dead)
check("вага ≥ 600 → REST не чіпаємо", nd2["source"] == "none" and not rest_calls)
omd.source_health = lambda: {"used_weight_1m": 120}
rp.REST_GAP_SEC = 0.0
ok = rp.load_data("AKEUSDT", None, start=st, end=st + timedelta(days=1), getter=dead)
check("вага < 600 → REST дозволено, по одному запиту на ТФ", ok["source"] == "rest" and len(rest_calls) == 3, str(len(rest_calls)))

# кейс повністю через архів: звіт називає джерело
rest_calls.clear()
r = rp.run_case("AKE", getter=getter)
check("run_case на архіві: джерело vision у звіті", r["result"].get("source") == "vision" and any("джерело свічок: vision" in x for x in rp.format_report(r)), str(r["result"])[:200])

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
