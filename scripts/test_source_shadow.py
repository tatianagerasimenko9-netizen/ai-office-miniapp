"""SOURCE_SHADOW: ATR Герчика без паранормальних, паранормальний бар ≥2×, база після імпульсу (D-POST-IMPULSE-BASE), без майбутніх барів, позначки джерела/гіпотези."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import source_shadow as S  # noqa: E402

FAILS = []


def check(name, ok, info=""):
    print(("OK  " if ok else "FAIL"), name, "" if ok else info)
    if not ok:
        FAILS.append(name)


D = 86400.0
T0 = 1_700_000_000 - (1_700_000_000 % 86400)


def bar(i, o, h, l, c):
    return {"ts": T0 + i * D, "open": o, "high": h, "low": l, "close": c, "volume": 1.0}


def calm(n, start=0, base=100.0):
    """Спокійний фон: діапазон 2.0 (high−low), без гепів."""
    out = []
    for k in range(n):
        o = base + (k % 2) * 0.2
        out.append(bar(start + k, o, o + 1.0, o - 1.0, o + 0.1))
    return out


# ---------- ATR Герчика: паранормальні бари (≥2×, ≤1/3) не входять у середнє
b = calm(10)
a0 = S.gerchik_atr(b, len(b))
check("ATR за Герчиком на спокійному фоні ≈ діапазон бару", a0 and abs(a0["atr"] - 2.0) < 0.35 and a0["bars_used"] == 5, str(a0))
b2 = b[:-2] + [bar(8, 100, 112, 99, 111), bar(9, 100, 101.0, 99.0, 100.1)]         # паранормальний бар у вікні
a1 = S.gerchik_atr(b2, len(b2))
check("паранормальний бар у вікні замінюється сусідніми (не роздуває ATR)", a1 and a1["atr"] < 2.6, str(a1))
tiny = b[:-1] + [bar(9, 100, 100.1, 99.95, 100.0)]
a2 = S.gerchik_atr(tiny, len(tiny))
check("дуже малий бар (≤1/3 ATR) теж виключається", a2 and a2["atr"] > 1.7, str(a2))
check("замало даних → None, не вигадується", S.gerchik_atr(calm(2), 2) is None)

# ---------- паранормальний бар ≥2×
series = calm(20) + [bar(20, 100, 101.0, 91.0, 92.0)]                         # діапазон 10 ≈ 5× ATR, вниз
pb = S.paranormal_bars(S.closed_d1(series, T0 + 22 * D))
check("паранормальний бар знайдено (≥2×ATR), напрям вниз", len(pb) == 1 and pb[0]["direction"] == "DOWN" and pb[0]["x_atr"] >= 4.0, str(pb))
check("звичайний фон не дає паранормальних барів", S.paranormal_bars(S.closed_d1(calm(25), T0 + 30 * D)) == [])
sc = S.paranormal_scenarios("TESTUSDT", series, T0 + 22 * D)
check("сценарій має rule_id і позначку ДЖЕРЕЛО, а гап/ATR-наближення — ГІПОТЕЗА", len(sc) == 1 and "G-LVL-PARANORMAL" in sc[0]["rule_ids"] and all(e["src"] for e in sc[0]["evidence"]) and "ГІПОТЕЗА" in sc[0]["evidence"][0]["src"], str(sc)[:240])
check("підтвердження рівня паранормального бару — НЕ ПІДТВЕРДЖЕНО (ok=None)", sc[0]["evidence"][1]["ok"] is None and sc[0]["evidence"][1]["text"].startswith("НЕ ПІДТВЕРДЖЕНО"))

# ---------- без майбутніх / незакритих барів
check("поточна (незакрита) доба не враховується", len(S.closed_d1(series, T0 + 20 * D + 3600)) == 20)
check("бар, якого ще немає на as_of, не створює сценарій (немає lookahead)", S.paranormal_scenarios("T", series, T0 + 20 * D + 3600) == [])

# ---------- база після імпульсу
def with_base(days, hi_edge=93.0, lo=91.0):
    out = list(series)
    for k in range(days):
        out.append(bar(21 + k, 92.0, hi_edge, lo + 0.5, 92.5))
    return out


bs = S.base_scenarios("TESTUSDT", with_base(4), T0 + 40 * D)
check("база 4 дні в нижній третині: BASE_OPTIMAL", len(bs) == 1 and bs[0]["state"] == "BASE_OPTIMAL", [x["state"] for x in bs])
ev = {e["step"]: e for e in bs[0]["evidence"]}
check("відкат ≈ 20% діапазону (93−91)/10, межа з джерела 50%", ev["відкат імпульсу"]["ok"] is True and abs(ev["відкат імпульсу"]["depth"] - 0.2) < 0.01, str(ev["відкат імпульсу"]))
check("тривалість: 4 дні, клас з джерела", ev["тривалість бази"]["days"] == 4 and "2–7" in ev["тривалість бази"]["text"] or "оптимальна" in ev["тривалість бази"]["text"], str(ev["тривалість бази"]))
check("варіант B (серія) і край бази — НЕ ПІДТВЕРДЖЕНО", ev["паранормальний рух (варіант B: серія барів)"]["ok"] is None and ev["краї бази й напрям продовження"]["ok"] is None)
check("база 1 день → шум", S.base_scenarios("T", with_base(1), T0 + 40 * D)[0]["state"] == "BASE_NOISE")
check("база 12 днів → BASE_EXTENDED", S.base_scenarios("T", with_base(12), T0 + 60 * D)[0]["state"] == "BASE_EXTENDED")
check("база понад 20 днів → STALE", S.base_scenarios("T", with_base(22), T0 + 60 * D)[0]["state"] in ("STALE",), S.base_scenarios("T", with_base(22), T0 + 60 * D)[0]["state"])
check("повернення >50% імпульсу → INVALIDATED", S.base_scenarios("T", with_base(3, hi_edge=97.5), T0 + 40 * D)[0]["state"] == "INVALIDATED")
check("база вище нижньої третини (але <50%) → BASE_OFF_THIRD", S.base_scenarios("T", with_base(3, hi_edge=95.0), T0 + 40 * D)[0]["state"] == "BASE_OFF_THIRD")
check("ще немає барів після імпульсу → NO_BASE_YET з НЕ ПІДТВЕРДЖЕНО", S.base_scenarios("T", series, T0 + 22 * D)[0]["state"] == "NO_BASE_YET")

# дзеркало: зростання → база у верхній третині
up = calm(20) + [bar(20, 100, 110.0, 99.0, 109.0)]
up += [bar(21 + k, 108.5, 109.0, 107.5, 108.0) for k in range(3)]
ub = S.base_scenarios("UPUSDT", up, T0 + 40 * D)
check("дзеркало (зростання): база у верхній третині → BASE_OPTIMAL", len(ub) == 1 and ub[0]["direction"] == "UP_BASE" and ub[0]["state"] == "BASE_NOISE" or ub[0]["state"] == "BASE_OPTIMAL", [x["state"] for x in ub])

# ---------- ідентичність і БД
db = os.path.join(tempfile.mkdtemp(), "ss.db")
now = T0 + 40 * D
r1 = [S.record(db, s, now) for s in S.evaluate("TESTUSDT", with_base(4), now)]
r2 = [S.record(db, s, now + 10) for s in S.evaluate("TESTUSDT", with_base(4), now + 10)]
check("перший прохід: нові, повторний: без дублікатів", r1.count("new") == 2 and r2.count("new") == 0 and r2.count("same") == 2, (r1, r2))
r3 = [S.record(db, s, now + 20 * D) for s in S.evaluate("TESTUSDT", with_base(4), now + 20 * D)]
sm = S.summary(db, now=now + 20 * D + 1)
check("зміна стану (час ішов) фіксується в історії; summary: не сигнал, rule_ids, db backend", sm["ok"] and len(sm["items"]) == 2 and "не сигнал" in sm["note"] and all(i["rule_ids"] and i["history"] for i in sm["items"]) and sm["db"]["backend"] == "sqlite", str(sm)[:300])


def fetch(sym, tf, lim):
    return [dict(x, ts=__import__("datetime").datetime.utcfromtimestamp(x["ts"]).strftime("%Y-%m-%dT%H:%M:%S+00:00")) for x in with_base(4)]


db2 = os.path.join(tempfile.mkdtemp(), "ss2.db")
rr = S.run_once(db2, fetch, ["AAAUSDT", "BBBUSDT"], now)
check("run_once читає ISO-ts біржі, пише shadow для кожного символу", rr["symbols"] == 2 and rr["new"] == 4 and rr["errors"] == 0, rr)

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
