"""Тести shadow-спостерігача методики Дарії: без майбутніх барів, без вигаданих порогів, чесний NOT_AVAILABLE."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import daria_shadow as D

FAILS = []


def check(name, ok, info=""):
    print(("OK  " if ok else "FAIL"), name, "" if ok else info)
    if not ok:
        FAILS.append(name)


def bars(n, base=100.0, step=0.1, t0=0):
    return [{"ts": t0 + 900 * i, "open": base + step * i, "high": base + step * i + 0.3, "low": base + step * i - 0.1, "close": base + step * i + 0.2, "volume": 100.0} for i in range(n)]


c = bars(30)
dec = c[24]["ts"] + 900
r = D.observe("LONG", 103.0, c, dec, next_obstacle=106.0)
check("використано лише бари, що закрились до моменту рішення", r["bars_used"] <= 25 and r["status"] == "OBSERVED", str(r["bars_used"]))
c2 = [dict(b) for b in c]
for b in c2[25:]:
    b["high"] += 50
    b["low"] -= 50
r2 = D.observe("LONG", 103.0, c2, dec, next_obstacle=106.0)
check("майбутні бари не впливають на результат", {k: v for k, v in r.items() if k != "lines"} == {k: v for k, v in r2.items() if k != "lines"})
check("вищі мінімуми → підтиснення до опору для LONG", r["squeeze_share"] == 1.0, str(r["squeeze_share"]))
rs = D.observe("SHORT", 103.0, c, dec)
check("для SHORT ті самі бари не дають підтиснення до підтримки", rs["squeeze_share"] == 0.0 and rs["room_atr"] is None, str(rs))
check("порогів немає: пояснення прямо це каже", "Пороги" in r["lines"][-1] and "thresholds" in r)
few = D.observe("LONG", 100.0, bars(4), 10 ** 9)
check("замало даних → NOT_AVAILABLE, нічого не вигадано", few["status"] == "NOT_AVAILABLE" and "reason" in few)
v = bars(30)
for b in v[-3:]:
    b["volume"] = 400.0
    b["close"] = v[-4]["close"] + 0.05
vo = D.observe("LONG", 103.0, v, v[-1]["ts"] + 900)
check("обсяг без прогресу ціни читається як боротьба/поглинання", vo["volume_x_result"] and "поглинання" in vo["volume_x_result"]["reading"], str(vo["volume_x_result"]))
print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
