"""Шар «Рівні Лева» для графіка Mini App: зони найближчі до ціни, дзеркальні позначено, без свічок — чесно порожньо."""
import os
import sys

os.environ["OFFICE_MINI_FIXTURE"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import office_mini_v2 as m  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


r = m.levels_payload("BTCUSDT", "H1")
check("відповідь ok, є symbol/tf і примітка «не вхід»", r["ok"] and r["symbol"] == "BTCUSDT" and "не вхід" in r["note"], str(r)[:200])
check("зон не більше 6", len(r["zones"]) <= 6)
check("кожна зона має lo ≤ hi і touches ≥ 2", all(z["lo"] <= z["hi"] and z["touches"] >= 2 for z in r["zones"]))
last = float(m.candles_payload("BTCUSDT", "H1", 300)["candles"][-1]["close"])
d = [min(abs(z["lo"] - last), abs(z["hi"] - last)) for z in r["zones"]]
check("зони відсортовано за близькістю до ціни", d == sorted(d), str(d))
check("у fixture PDH/PDL не вигадуються (мережі немає)", r["previous"] == {})
check("endpoint зареєстровано без БД", "/api/v2/levels" in m.DB_FREE_PATHS)

import office_levels as lv  # noqa: E402

# дзеркальна зона: рівень був і опором, і підтримкою
rows = []
import math  # noqa: E402

for i in range(120):
    c = 100 + 2.0 * math.sin(i / 4.0)
    rows.append({"ts": f"2026-01-01T{(i // 4) % 24:02d}:{(i % 4) * 15:02d}:00+00:00", "open": c, "high": c + 0.3, "low": c - 0.3, "close": c, "volume": 1})
zs = lv.zones(rows)
check("office_levels.zones повертає зони з полем mirror", all("mirror" in z for z in zs) and len(zs) >= 1)

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
