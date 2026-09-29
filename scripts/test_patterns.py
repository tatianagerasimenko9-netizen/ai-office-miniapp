#!/usr/bin/env python3
"""Потрійне/подвійне дно: перевірюване правило (допуск 0,3% або 0,5×ATR, ≥3 свічки між мінімумами, підтвердження закриттям за шиєю)."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_patterns as P  # noqa: E402
from office_confluence import detect_ltf_confirms  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def mk(closes, lows_at=None, highs_at=None):
    rows = []
    for i, c in enumerate(closes):
        lo = c - 0.15
        hi = c + 0.15
        if lows_at and i in lows_at:
            lo = lows_at[i]
        if highs_at and i in highs_at:
            hi = highs_at[i]
        rows.append({"ts": (T0 + timedelta(minutes=15 * i)).isoformat(), "open": c, "high": hi, "low": lo, "close": c})
    return rows


# базовий шум ~100.4, мінімуми на 5, 11, 17 (розкид 0.06%), піки між ними до 101.2 → шия 101.2
base = [100.5, 100.6, 100.4, 100.3, 100.2, 99.3, 100.2, 100.5, 100.9, 100.7, 100.3, 99.4, 100.2, 100.6, 101.0, 100.6, 100.3, 99.35, 100.1, 100.5]
lows = {5: 99.00, 11: 99.05, 17: 98.98}
highs = {8: 101.2}
NOW = (T0 + timedelta(days=2)).timestamp()

rows = mk(base + [100.9], lows, highs)  # без закриття за шиєю
p = P.find_multi(rows, direction="LONG", n=3, zone_lo=98.5, zone_hi=99.5, now_ts=NOW)
assert p and p["kind"] == "triple_bottom" and not p["confirmed"], p
assert [round(e["price"], 2) for e in p["extremes"]] == [99.0, 99.05, 98.98] and abs(p["neckline"] - 101.2) < 1e-9

rows_c = mk(base + [100.9, 101.5], lows, highs)  # закриття 101.5 > шиї 101.2
p = P.find_multi(rows_c, direction="LONG", n=3, zone_lo=98.5, zone_hi=99.5, now_ts=NOW)
assert p and p["confirmed"] and p["confirm"]["close"] == 101.5, p
hits = detect_ltf_confirms(direction="LONG", candles_ltf=rows_c, zone_lo=98.5, zone_hi=99.5, now_ts=NOW)
assert "triple_bottom" in hits, hits
hits0 = detect_ltf_confirms(direction="LONG", candles_ltf=rows, zone_lo=98.5, zone_hi=99.5, now_ts=NOW)
assert "triple_bottom" not in hits0 and "double_bottom" not in hits0, ("без закриття за шиєю патерну як підтвердження немає", hits0)

# мінімуми надто розкидані → не патерн
bad = mk(base + [100.9, 101.5], {5: 99.00, 11: 98.20, 17: 98.98}, highs)
assert P.find_multi(bad, direction="LONG", n=3, zone_lo=97.5, zone_hi=99.5, now_ts=NOW) is None
# менше 3 свічок між мінімумами → не патерн
close_lows = mk([100.5, 100.6, 100.4, 100.3, 99.3, 100.2, 99.3, 100.2, 99.3, 100.4, 100.6, 100.7, 100.9, 101.5], {4: 99.0, 6: 99.02, 8: 98.99}, highs)
assert P.find_multi(close_lows, direction="LONG", n=3, zone_lo=98.5, zone_hi=99.5, now_ts=NOW) is None
# закриття нижче мінімуму на допуск після патерну → скасовано
broken = mk(base + [100.6, 98.0], lows, highs)
assert P.find_multi(broken, direction="LONG", n=3, zone_lo=98.5, zone_hi=99.5, now_ts=NOW) is None
# мінімуми поза зоною → не патерн «у зоні»
assert P.find_multi(rows_c, direction="LONG", n=3, zone_lo=95.0, zone_hi=96.0, now_ts=NOW) is None
# свічка, що ще формується, не підтверджує
live = mk(base + [100.9, 101.5])
live[-1]["ts"] = datetime.fromtimestamp(NOW - 300, tz=timezone.utc).isoformat()
live[-2]["ts"] = datetime.fromtimestamp(NOW - 300 - 900, tz=timezone.utc).isoformat()
for i, r in enumerate(live[:-2]):
    r["ts"] = datetime.fromtimestamp(NOW - 300 - 900 * (len(live) - 1 - i), tz=timezone.utc).isoformat()
for i, v in lows.items():
    live[i]["low"] = v
live[8]["high"] = 101.2
pl = P.find_multi(live, direction="LONG", n=3, zone_lo=98.5, zone_hi=99.5, now_ts=NOW)
assert pl is None or not pl["confirmed"], "незакрита свічка не підтверджує"

# SHORT: дзеркало — потрійна вершина
inv = [200 - (x - 100) for x in base + [100.9, 101.5]]
srows = mk(inv, highs_at={5: 201.0, 11: 200.95, 17: 201.02}, lows_at={8: 198.8})
sp = P.find_multi(srows, direction="SHORT", n=3, zone_lo=200.5, zone_hi=201.5, now_ts=NOW)
assert sp and sp["kind"] == "triple_top" and sp["confirmed"], sp
print("OK patterns: triple/double bottom/top with tolerance, spacing, neckline close, invalidation, zone, closed candles")
