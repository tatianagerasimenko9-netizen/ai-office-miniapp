#!/usr/bin/env python3
"""SMC/Вайкоф у підтвердженні входу: BOS/CHoCH (раніше відкидались списком FORMAL_TAGS), sweep, spring — потрапляють у detect_ltf_confirms біля зони."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_confluence as cf  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = (T0 + timedelta(days=5)).timestamp()
FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def ts(i):
    return (T0 + timedelta(minutes=15 * i)).isoformat()


def walk(vertices, legs, pad=0.15, vol=100.0):
    closes = [vertices[0]]
    for (a, b), n in zip(zip(vertices, vertices[1:]), legs):
        for k in range(1, n + 1):
            closes.append(a + (b - a) * k / n)
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        rows.append({"ts": ts(i), "open": prev, "high": c + pad, "low": c - pad, "close": c, "volume": vol})
        prev = c
    return rows


check("bos і choch у списку формальних тегів і мають українські назви", "bos" in cf.FORMAL_TAGS and "choch" in cf.FORMAL_TAGS and cf.CONFIRM_UA.get("bos") and cf.CONFIRM_UA.get("choch"))

up = walk([100, 106, 103, 110, 107, 114, 111, 117], [4, 3, 4, 3, 4, 3, 4])      # HH/HL → BOS LONG (закриття за свінг-хаєм 114)
h = cf.detect_ltf_confirms(direction="LONG", candles_ltf=up, zone_lo=115.5, zone_hi=118.0, now_ts=NOW)
check("LONG: BOS біля зони потрапляє в підтвердження", "bos" in h, str(h))
check("SHORT на тому ж графіку BOS не отримує", "bos" not in cf.detect_ltf_confirms(direction="SHORT", candles_ltf=up, zone_lo=115.5, zone_hi=118.0, now_ts=NOW))

dn = walk([120, 114, 117, 108, 111, 102, 105, 113], [4, 3, 4, 3, 4, 3, 6])      # LH/LL → CHoCH LONG (закриття за 111)
h2 = cf.detect_ltf_confirms(direction="LONG", candles_ltf=dn, zone_lo=111.5, zone_hi=114.0, now_ts=NOW)
check("LONG: CHoCH біля зони потрапляє в підтвердження", "choch" in h2, str(h2))

far = cf.detect_ltf_confirms(direction="LONG", candles_ltf=up, zone_lo=150.0, zone_hi=152.0, now_ts=NOW)
check("зона далеко від ціни → тегів SMC немає (лише біля зони)", "bos" not in far and "choch" not in far, str(far))

# sweep пулу і spring теж доходять до підтвердження (перевіряється повним ланцюгом)
base = walk([100, 110, 104, 110.05, 104, 106], [5, 5, 5, 5, 3])
sw = base + [{"ts": ts(len(base)), "open": 106, "high": 111.0, "low": 105.8, "close": 109.4, "volume": 120}]
sw += [{"ts": ts(len(sw)), "open": 109.4, "high": 109.6, "low": 108.0, "close": 108.4, "volume": 90}]
hs = cf.detect_ltf_confirms(direction="SHORT", candles_ltf=sw, zone_lo=108.0, zone_hi=111.5, now_ts=NOW)
check("SHORT: sweep пулу ліквідності доходить до підтвердження", "sweep_pool" in hs, str(hs))

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
