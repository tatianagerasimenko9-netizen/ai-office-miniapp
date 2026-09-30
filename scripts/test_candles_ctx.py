#!/usr/bin/env python3
"""Свічкові моделі лише в контексті: біля зони, з обсягом, ATR, в активну сесію."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_candles as C  # noqa: E402

T0 = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)      # активні Лондон і Нью-Йорк (літо)
NOW = (T0 + timedelta(days=1)).timestamp()


def mk(tail, t0=T0, n=30):
    rows = []
    for i in range(n):
        base = 101.0 + (0.15 if i % 2 else -0.15)
        rows.append({"ts": (t0 + timedelta(minutes=15 * i)).isoformat(), "open": base, "high": base + 0.3, "low": base - 0.3, "close": base + (0.05 if i % 2 else -0.05), "volume": 100})
    for j, r in enumerate(tail):
        r = dict(r); r["ts"] = (t0 + timedelta(minutes=15 * (n + j))).isoformat(); r.setdefault("volume", 200); rows.append(r)
    return rows


def kinds(rows, side="LONG", zone=(100.0, 100.5), now=NOW):
    return [t["kind"] for t in C.tags_for(rows, side, zone[0], zone[1], now)]


pin = mk([{"open": 100.8, "high": 100.9, "low": 99.4, "close": 100.85}])
assert kinds(pin) == ["pin_bar"], kinds(pin)
assert kinds(mk([{"open": 100.8, "high": 100.9, "low": 99.4, "close": 100.85, "volume": 100}])) == [], "без сплеску обсягу — нема"
assert kinds(pin, zone=(110.0, 111.0)) == [], "далеко від зони — нема"
late = mk([{"open": 100.8, "high": 100.9, "low": 99.4, "close": 100.85}], t0=datetime(2026, 12, 9, 14, 15, tzinfo=timezone.utc))
assert C.tags_for(late, "LONG", 100.0, 100.5, datetime(2026, 12, 11, tzinfo=timezone.utc).timestamp()) == [], "поза активними сесіями — нема"
assert kinds(pin, side="SHORT") == [], "тінь вниз — для SHORT не pin"
spin = mk([{"open": 100.4, "high": 101.6, "low": 100.3, "close": 100.35}])
assert kinds(spin, side="SHORT", zone=(101.0, 101.6)) == ["pin_bar"], kinds(spin, side="SHORT", zone=(101.0, 101.6))
# поглинання
eng = mk([{"open": 100.9, "high": 101.0, "low": 100.3, "close": 100.4}, {"open": 100.3, "high": 101.5, "low": 100.2, "close": 101.4}])
assert "engulfing_ctx" in kinds(eng), kinds(eng)
# inside bar: мати 99.6–101.0, inside 99.9–100.7 (біля зони), закриття 101.2 > 101.0
ib = mk([{"open": 100.0, "high": 101.0, "low": 99.6, "close": 100.6}, {"open": 100.3, "high": 100.7, "low": 99.9, "close": 100.4}, {"open": 100.5, "high": 101.4, "low": 100.4, "close": 101.2}])
assert "inside_bar_break" in kinds(ib), kinds(ib)
ib2 = mk([{"open": 100.0, "high": 101.0, "low": 99.6, "close": 100.6}, {"open": 100.3, "high": 100.7, "low": 99.9, "close": 100.4}, {"open": 100.5, "high": 100.9, "low": 100.4, "close": 100.8}])
assert "inside_bar_break" not in kinds(ib2), "без закриття за межею матері — нема"
# виснаження
ex = mk([{"open": 101.2, "high": 101.3, "low": 100.9, "close": 101.0, "volume": 110}, {"open": 101.0, "high": 101.1, "low": 100.6, "close": 100.7, "volume": 110},
         {"open": 100.7, "high": 100.8, "low": 100.3, "close": 100.4, "volume": 110}, {"open": 100.4, "high": 100.6, "low": 99.3, "close": 100.5, "volume": 320}])
assert "exhaustion" in kinds(ex), kinds(ex)
print("OK candles in context: pin bar, inside-bar break, engulfing, exhaustion — zone + volume + ATR + session required")
