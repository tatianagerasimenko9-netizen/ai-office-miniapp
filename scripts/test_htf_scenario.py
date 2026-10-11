"""HTF_STRONG_CANDLE_PULLBACK (shadow): послідовність кроків, відсутність майбутніх барів, чесне «НЕ ПІДТВЕРДЖЕНО», позначки джерела/гіпотези."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import htf_scenario as H  # noqa: E402

FAILS = []


def check(name, ok, info=""):
    print(("OK  " if ok else "FAIL"), name, "" if ok else info)
    if not ok:
        FAILS.append(name)


W = 14400
T0 = 1_700_000_000 - (1_700_000_000 % W)


def bar(i, o, h, l, c, v=100.0, w=W, t0=T0):
    return {"ts": t0 + i * w, "open": o, "high": h, "low": l, "close": c, "volume": v}


def htf_series(with_pullback=True, lost=False):
    b = []
    for i in range(27):                       # спокійний фон ~ діапазон 1.5
        b.append(bar(i, 100 + (i % 2) * 0.2, 100.9 + (i % 2) * 0.2, 99.4 + (i % 2) * 0.2, 100.2 + (i % 2) * 0.2))
    b.append(bar(27, 100, 100.5, 98.0, 99.0))                 # локальний мінімум 98 (початок імпульсу)
    b.append(bar(28, 99, 100.6, 98.8, 100.2))
    b.append(bar(29, 100.2, 100.8, 99.8, 100.4))
    b.append(bar(30, 100.4, 109.0, 100.0, 108.0, v=600.0))     # сильна свічка LONG: тіло 100.4–108
    for k, (o, hh, ll, cc) in enumerate([(108, 110.5, 107.5, 110), (110, 112, 109.8, 111.5), (111.5, 111.8, 110.0, 110.4), (110.4, 110.9, 109.0, 109.5)]):
        b.append(bar(31 + k, o, hh, ll, cc))                    # максимум імпульсу 112 і два нижчі бари після нього → підтверджений swing
    if with_pullback:
        for k, (o, hh, ll, cc) in enumerate([(109.5, 109.8, 107.0, 107.5), (107.5, 107.9, 105.5, 106.0)]):
            b.append(bar(35 + k, o, hh, ll, cc))
    if lost:
        b.append(bar(37, 106, 106.2, 98.5, 99.0))               # закриття нижче мінімуму сильної свічки (100.0)
    return b


def ltf(htf_last_ts, price_path, w):
    return [bar(i, p, p + 0.05, p - 0.05, p, w=w, t0=htf_last_ts + W - len(price_path) * w) for i, p in enumerate(price_path)]


h = htf_series()
as_of = h[-1]["ts"] + W
m15 = ltf(h[-1]["ts"], [110, 109, 108.5, 107.5, 107, 106.5, 106.2, 106.0], 900)
m5 = ltf(h[-1]["ts"], [106.0] * 6 + [105.9, 105.8, 105.9, 106.0, 106.1, 106.6], 300)      # у кінці — закриття вище максимуму 3 попередніх
res = H.evaluate("TESTUSDT", "4h", h, m15, m5, as_of)
check("знайдено один сценарій LONG на сильну свічку, id постійний", len(res) == 1 and res[0]["direction"] == "LONG" and res[0]["scenario_id"] == f"HTF|TESTUSDT|LONG|4h|{int(T0 + 30 * W)}", str(res)[:200])
r = res[0]
steps = {e["step"]: e for e in r["evidence"]}
check("крок 1: сильна свічка зафіксована з тілом, максимумом, мінімумом", steps["сильна свічка старшого ТФ"]["ok"] and "100.4" in steps["сильна свічка старшого ТФ"]["text"].replace("100,4", "100.4"))
check("крок 2: Fibonacci будується між підтвердженими swing-точками 98→112 з часом", steps["завершений імпульс і Fibonacci"]["ok"] and r["impulse"]["from"]["price"] == 98.0 and r["impulse"]["to"]["price"] == 112.0 and set(r["fib"]) == {"23.6%", "38.2%", "50%", "61.8%", "78.6%"}, str(r["impulse"]))
check("рівні Fibonacci — з джерела, точки — гіпотеза: позначки src присутні", "ДЖЕРЕЛО" in steps["завершений імпульс і Fibonacci"]["src"] and "ГІПОТЕЗА" in steps["завершений імпульс і Fibonacci"]["src"])
check("крок 3: збіги лише реальні (Fibonacci у тілі свічки), не вигадані", steps["збіг області свічки з Fibonacci/рівнями"]["ok"] is True and "у тілі свічки" in steps["збіг області свічки з Fibonacci/рівнями"]["text"])
check("крок 4: відкат у область зафіксований", steps["відкат"]["ok"] is True and r["state"] in ("IN_ZONE", "TRIGGERED"))
check("крок 5: M5-тригер підтверджений після входу в область → TRIGGERED", r["state"] == "TRIGGERED" and steps["точка входу на M5"]["ok"] is True, r["state"])
check("тригер M5 позначений як гіпотеза (не слова авторки)", "ГІПОТЕЗА" in steps["точка входу на M5"]["src"])

pl = r["plan"]
check("план після тригера: вхід = закриття тригера, цілі зі структури старшого ТФ (не кратність), стоп за екстремумом відкату",
      pl and pl["entry"] == 106.6 and pl["stop_extreme"] <= 106.0 and pl["targets"] and all("структура" in t["src"] for t in pl["targets"]) and pl["targets"][0]["price"] > pl["entry"], str(pl)[:300])
check("shadow-позначка would_be_ready не ввімкнена без обґрунтованого стопа", (pl["would_be_ready"] is False) or pl["recommended_stop"], str(pl["recommended_stop"]))

# без M5-підтвердження — лише IN_ZONE і «НЕ ПІДТВЕРДЖЕНО»
m5_no = ltf(h[-1]["ts"], [106.0, 106.0, 105.9, 105.8, 105.7, 105.6, 105.5, 105.4], 300)
r2 = H.evaluate("TESTUSDT", "4h", h, m15, m5_no, as_of)[0]
st2 = {e["step"]: e for e in r2["evidence"]}
check("без підтвердження на M5: IN_ZONE і текст «НЕ ПІДТВЕРДЖЕНО», не сигнал", r2["state"] == "IN_ZONE" and st2["точка входу на M5"]["ok"] is None and st2["точка входу на M5"]["text"].startswith("НЕ ПІДТВЕРДЖЕНО"), r2["state"])

# --- тригер M5 має бути в старшій області й свіжим (регресія: у production 13 з 49 сценаріїв одразу ставали TRIGGERED)
m15_early = ltf(h[-1]["ts"], [107.5] * 8, 900)                                          # ціна в області вже від початку вікна
m5_left = ltf(h[-1]["ts"], [106.0] * 14 + [110.5, 110.6, 110.7, 110.8, 110.9, 111.0], 300)   # єдиний пробій відбувся вже поза старшою областю (тіло до 108)
r7 = H.evaluate("TESTUSDT", "4h", h, m15_early, m5_left, as_of)[0]
st7 = {e["step"]: e for e in r7["evidence"]}
check("пробій M5 поза старшою областю → не TRIGGERED, пояснення «запізно»", r7["state"] != "TRIGGERED" and "запізно" in st7["точка входу на M5"]["text"], r7["state"] + " " + st7["точка входу на M5"]["text"])
m5_old = ltf(h[-1]["ts"], [106.0] * 4 + [106.6] + [106.0] * 20, 300)                     # пробій 20 барів тому
r8 = H.evaluate("TESTUSDT", "4h", h, m15_early, m5_old, as_of)[0]
check("застарілий M5-пробій → не TRIGGERED", r8["state"] != "TRIGGERED" and "застарів" in {e["step"]: e for e in r8["evidence"]}["точка входу на M5"]["text"])

# ціна ще не повернулась → WAIT_PULLBACK
h_wait = htf_series(with_pullback=False)
as_of_w = h_wait[-1]["ts"] + W
m15_w = ltf(h_wait[-1]["ts"], [110.2, 110.0, 109.8, 109.6], 900)
r3 = H.evaluate("TESTUSDT", "4h", h_wait, m15_w, [], as_of_w)[0]
check("ціна вище області → WAIT_PULLBACK (спостереження)", r3["state"] == "WAIT_PULLBACK", r3["state"])
check("до тригера плану немає", r2["plan"] is None and r3["plan"] is None)

# втрата актуальності
hl = htf_series(lost=True)
m15_l = ltf(hl[-1]["ts"], [99.5, 99.2, 99.0], 900)
r4 = H.evaluate("TESTUSDT", "4h", hl, m15_l, [], hl[-1]["ts"] + W)[0]
check("закриття за протилежним краєм сильної свічки → INVALIDATED", r4["state"] == "INVALIDATED", r4["state"])

# жодних майбутніх барів: додаємо «майбутній» бар після as_of — результат не змінюється
fut = [dict(b) for b in h] + [bar(len(h), 106, 200, 50, 60, v=900)]
r5 = H.evaluate("TESTUSDT", "4h", fut, m15, m5, as_of)[0]
check("майбутній бар (після as_of) не впливає на результат", r5["state"] == r["state"] and r5["impulse"] == r["impulse"])

# немає сильної свічки → порожньо, нічого не вигадується
flat = [bar(i, 100, 100.9, 99.4, 100.2) for i in range(60)]
check("без сильної свічки сценаріїв немає", H.evaluate("T", "4h", flat, m15, m5, flat[-1]["ts"] + W) == [])
# сильна свічка є, але імпульс не завершений (немає підтвердженого swing high після неї) → НЕ ПІДТВЕРДЖЕНО, state NO_IMPULSE
hs_ = htf_series(with_pullback=False)[:35]       # обрізаємо після максимуму: потрібних двох нижчих барів ще немає
r6 = H.evaluate("T", "4h", hs_, m15, m5, hs_[-1]["ts"] + W)
st6 = {e["step"]: e for e in r6[0]["evidence"]} if r6 else {}
check("імпульс не завершений → «НЕ ПІДТВЕРДЖЕНО», Fibonacci не будується", (not r6) or (r6[0]["state"] == "NO_IMPULSE" and r6[0]["fib"] is None and st6["завершений імпульс і Fibonacci"]["ok"] is None), str(r6)[:200])
check("кожен доказ має джерело (src)", all(e.get("src") for e in r["evidence"]))
# --- shadow-запис у БД: один сценарій на сильну свічку, історія станів, повторний прохід не дублює
import os, tempfile  # noqa: E401
import office_bridge as OB  # noqa: E402
db = os.path.join(tempfile.mkdtemp(), "htf.db")
OB.init_office_db(db)
check("запис нового сценарію", H.record(db, r, as_of) == "new")
check("повторний прохід без змін не дублює", H.record(db, r, as_of + 60) == "same" and OB._fetchall(db, "SELECT COUNT(*) FROM office2_htf_shadow")[0][0] == 1)
r_prev = dict(r, state="IN_ZONE")
check("зміна стану фіксується в історії", H.record(db, r_prev, as_of + 120) == "changed" and len(__import__("json").loads(OB._fetchall(db, "SELECT state_history FROM office2_htf_shadow")[0][0])) == 2)
def _fetch(sym, tf, lim):
    from datetime import datetime, timezone
    src = {"1d": [], "4h": h, "15m": m15, "5m": m5}[tf]
    return [dict(b, ts=datetime.fromtimestamp(b["ts"], tz=timezone.utc).isoformat()) for b in src]
db2 = os.path.join(tempfile.mkdtemp(), "htf2.db")
OB.init_office_db(db2)
rr = H.run_once(db2, _fetch, ["TESTUSDT"], as_of)
check("прохід по universe читає свічки з ISO-ts (формат біржі) і пише shadow", rr["errors"] == 0 and rr["new"] == 1 and OB._fetchall(db2, "SELECT state FROM office2_htf_shadow")[0][0] == "TRIGGERED", str(rr))

sm = H.summary(db2, now=as_of + 60)
check("summary для Mini App: сценарій зі станом, доказами з позначкою джерела і нотатка «не сигнал»", sm["ok"] and len(sm["items"]) == 1 and sm["items"][0]["state"] == "TRIGGERED" and all(e.get("src") for e in sm["items"][0]["evidence"]) and "не сигнал" in sm["note"] and sm["db"]["backend"] == "sqlite", str(sm)[:200])

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
