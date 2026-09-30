#!/usr/bin/env python3
"""Рівні як зони: кластери, дзеркальні, PDH/PDL/тижневі, хибний пробій, закріплення, ретест."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_levels as L  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = (T0 + timedelta(days=5)).timestamp()


def walk(vertices, legs, pad=0.15):
    closes = [vertices[0]]
    for (a, b), n in zip(zip(vertices, vertices[1:]), legs):
        for k in range(1, n + 1):
            closes.append(a + (b - a) * k / n)
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        rows.append({"ts": (T0 + timedelta(minutes=15 * i)).isoformat(), "open": prev, "high": c + pad, "low": c - pad, "close": c, "volume": 100})
        prev = c
    return rows


# підтримка ≈100: два відскоки мінімумами 100.0 і 100.1
sup = walk([104, 100.0, 106, 100.1, 105, 103], [4, 4, 4, 4, 3])
zs = L.zones(sup, NOW)
assert len(zs) == 1 and zs[0]["touches"] == 2 and 99.7 < zs[0]["lo"] < 100.0 and 99.9 < zs[0]["hi"] < 100.1 and not zs[0]["mirror"], zs
# одиночний дотик — не рівень
assert L.zones(walk([104, 100.0, 106, 103.5, 105, 104], [4, 4, 4, 4, 3]), NOW) == []
# дзеркальний рівень: спершу опір (максимум ≈100.1), потім підтримка (мінімум ≈100.0)
mir = walk([96, 100.05, 97, 103, 100.0, 106, 104], [4, 4, 4, 4, 4, 3])
zm = L.zones(mir, NOW)
assert zm and any(z["mirror"] for z in zm), zm
# PDH/PDL і тижневі: береться попередня ЗАВЕРШЕНА свічка
d = [{"high": 10, "low": 5}, {"high": 12, "low": 6}, {"high": 11, "low": 7}]
w = [{"high": 20, "low": 3}, {"high": 25, "low": 2}, {"high": 22, "low": 4}]
assert L.previous_levels(d, w) == {"PDH": 12.0, "PDL": 6.0, "PWH": 25.0, "PWL": 2.0}
# хибний пробій підтримки: остання свічка — тінь 99.5 під зоною, закриття 100.9
fb = sup + [{"ts": (T0 + timedelta(minutes=15 * len(sup))).isoformat(), "open": 101.5, "high": 101.6, "low": 99.5, "close": 100.9, "volume": 150}]
assert [t["kind"] for t in L.tags_for(fb, "LONG", 99.9, 100.6, NOW)] == ["level_false_break"], L.tags_for(fb, "LONG", 99.9, 100.6, NOW)
assert L.tags_for(fb, "LONG", 120.0, 121.0, NOW) == [], "зона сценарію далеко від рівня"
assert L.tags_for(fb, "SHORT", 99.9, 100.6, NOW) == [], "для SHORT це не хибний пробій підтримки"
# опір ≈110: два піки 110.0/110.1; закріплення над ним (2 закриття) і ретест
res = walk([104, 110.0, 105, 110.1, 106], [4, 4, 4, 4])
res += walk([106, 111.5, 111.8], [2, 2])[1:]            # два закриття над 110.1+
hold = res
assert "level_hold" in [t["kind"] for t in L.tags_for(hold, "LONG", 109.8, 110.4, NOW)], L.tags_for(hold, "LONG", 109.8, 110.4, NOW)
ret = hold + [{"ts": (T0 + timedelta(minutes=15 * len(hold))).isoformat(), "open": 111.0, "high": 111.3, "low": 110.0, "close": 111.0, "volume": 100}]
kinds = [t["kind"] for t in L.tags_for(ret, "LONG", 109.8, 110.4, NOW)]
assert "level_retest" in kinds, kinds
# без закріплення (одна свічка за зоною) — hold/retest немає
one = walk([104, 110.0, 105, 110.1, 106], [4, 4, 4, 4]) + walk([106, 111.5], [2])[1:]
assert L.tags_for(one, "LONG", 109.8, 110.4, NOW) == [], L.tags_for(one, "LONG", 109.8, 110.4, NOW)
print("OK levels: zones, mirror, PDH/PDL/weekly, false break, hold, retest")

from office_confluence import detect_ltf_confirms  # noqa: E402

assert "level_false_break" in detect_ltf_confirms(direction="LONG", candles_ltf=fb, zone_lo=99.8, zone_hi=100.6, now_ts=NOW)
print("OK levels → confirms integration")
