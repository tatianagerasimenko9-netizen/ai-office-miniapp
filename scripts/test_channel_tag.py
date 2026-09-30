"""Тег channel_edge: зона на межі регресійного каналу (LONG — нижня межа, канал не вниз, межу втримано; SHORT — дзеркально)."""
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import office_regression_channel as rc  # noqa: E402
import office_confluence as cf  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def series(n, slope, base=100.0, amp=1.5):
    out = []
    for i in range(n):
        c = base + slope * i + amp * math.sin(i / 3.0)
        out.append({"open": c - 0.1, "high": c + 0.4, "low": c - 0.4, "close": c, "volume": 10.0,
                    "ts": (T0 + timedelta(minutes=15 * i)).isoformat()})
    return out


def zone_at(rows, which, pad=0.3):
    ch = rc.regression_channel(rows, length=min(100, len(rows) - 1), deviation=2.0)
    e = ch["lower_end"] if which == "lower" else ch["upper_end"]
    return ch, e - pad, e + pad


up = series(140, 0.12)
ch, zl, zh = zone_at(up, "lower")
mid = ch["mid_end"]
up[-2]["close"] = mid          # остання закрита свічка вище нижньої межі
check("LONG: зона на нижній межі висхідного каналу → тег", [t["kind"] for t in rc.tags_for(up, "LONG", zl, zh)] == ["channel_edge"])
check("тег потрапляє у підтвердження конфлюенсу", "channel_edge" in cf.FORMAL_TAGS and "channel_edge" in cf.CONFIRM_UA)
check("SHORT на нижній межі — тегу нема", rc.tags_for(up, "SHORT", zl, zh) == [])

far_lo, far_hi = mid - 0.3, mid + 0.3                       # зона посередині каналу, не на межі
check("зона не на межі → тегу нема", rc.tags_for(up, "LONG", far_lo, far_hi) == [])

broken = [dict(r) for r in up]
broken[-2]["close"] = zl - 3.0                              # межу НЕ втримано (закриття під нею)
check("закриття під нижньою межею → тегу нема", rc.tags_for(broken, "LONG", zl, zh) == [])

down = series(140, -0.12)
chd, dzl, dzh = zone_at(down, "lower")
down[-2]["close"] = chd["mid_end"]
check("LONG у низхідному каналі (ловля ножа) → тегу нема", rc.tags_for(down, "LONG", dzl, dzh) == [])

chd2, uzl, uzh = zone_at(down, "upper")   # закриття вже виставлено вище; після зони дані не чіпаємо
check("SHORT: зона на верхній межі низхідного каналу → тег", [t["kind"] for t in rc.tags_for(down, "SHORT", uzl, uzh)] == ["channel_edge"])

check("замало свічок → тегу нема", rc.tags_for(up[:20], "LONG", zl, zh) == [])
check("некоректна зона/напрямок → тегу нема", rc.tags_for(up, "LONG", "x", None) == [] and rc.tags_for(up, "FLAT", zl, zh) == [])

# інтеграція: detect_ltf_confirms віддає тег, коли ціна біля зони
hits = cf.detect_ltf_confirms(direction="LONG", candles_ltf=up, zone_lo=zl, zone_hi=zh)
check("detect_ltf_confirms віддає channel_edge біля зони", "channel_edge" in hits, str(hits))

# звірка з Pine get_channel: нахил = справжній нахил OLS (linreg(len,0)-linreg(len,1) на одному вікні)
_m = 0.05
_line = [100.0 + _m * i for i in range(300)]
_ic, _ey, _dev, _sl = rc.get_channel(_line, 100)
check("нахил каналу = нахил прямої (Pine linreg offset на одному вікні)", abs(_sl - _m) < 1e-9, str(_sl))
check("відхилення ідеальної прямої = |нахил| (як у Pine: slope*(len-x))", abs(_dev - _m) < 1e-9, str(_dev))
_noisy = [100.0 + 0.05 * i + (1.0 if i % 2 else -1.0) for i in range(300)]
_ic2, _ey2, _dev2, _sl2 = rc.get_channel(_noisy, 100)
check("шум ±1 не подвоює нахил і відхилення", abs(_sl2 - 0.05) < 0.01 and 0.9 < _dev2 < 1.2, f"{_sl2} {_dev2}")

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
