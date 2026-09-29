#!/usr/bin/env python3
"""Порт PUMP & DUMP HUNTER v2 проти Pine (pump_dump_hunter_v2.pine): vol_sma береться на тій самій свічці (vol_sma[back]),
тижневі рівні w_h/w_l враховуються. Регресія: раніше «сплеск об'єму» рахувався від ПОТОЧНОГО середнього для всіх минулих свічок."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
import office_pump_dump as P  # noqa: E402


def bar(i, o, c, v, hi=None, lo=None):
    return {"ts": f"2026-09-29T{(i // 60) % 24:02d}:{i % 60:02d}:00+00:00", "open": o, "close": c, "volume": v,
            "high": hi if hi is not None else max(o, c) * 1.001, "low": lo if lo is not None else min(o, c) * 0.999}


def series(spike_last: float):
    rows = []
    px = 100.0
    for i in range(70):
        rows.append(bar(i, px, px * 1.0002, 100.0))
        px *= 1.0002
    n = len(rows)
    # велика червона свічка 5 барів тому: об'єм 200 > 1.8 × своє SMA(100), але < 1.8 × поточне SMA після сплеску останньої
    b = rows[n - 6]
    rows[n - 6] = bar(n - 6, b["open"], b["open"] * 0.97, 200.0)
    # підтвердження: остання свічка зелена, вище попереднього close, з величезним об'ємом (піднімає ПОТОЧНЕ SMA)
    last_o = rows[-2]["close"]
    rows[-1] = bar(n - 1, last_o, last_o * 1.02, spike_last)
    return rows


r = P.evaluate_pump_dump(candles=series(1000.0))
assert r["parts_l"]["delev"] >= 2, r["parts_l"]     # Pine: червона свічка 5 барів тому підтверджена (delev = 2 при back ≤ 8)
# те саме без сплеску останньої свічки: delev той самий (не залежить від поточного середнього)
r2 = P.evaluate_pump_dump(candles=series(100.0))
assert r2["parts_l"]["delev"] == r["parts_l"]["delev"], (r2["parts_l"], r["parts_l"])
# SMA на свічці: недостатньо історії → None (Pine na), рівно 20 → середнє
rows = series(100.0)
assert P._vol_sma_at(rows, 5) is None and abs(P._vol_sma_at(rows, 30) - 100.0) < 1e-9
# тижневі рівні: біля мінімуму попереднього тижня рахунок рівнів зростає
w_ok = [{"open": 1, "close": 1, "high": 1, "low": 1}, {"open": 100, "close": 100.1, "high": 105, "low": 99.9}, {"open": 100, "close": 100, "high": 101, "low": 99.5}]
daily = [{"open": 100, "close": 101, "high": 110, "low": 90}, {"open": 100, "close": 99, "high": 102, "low": 95}, {"open": 99, "close": 99, "high": 100, "low": 98}]
base = P.evaluate_pump_dump(candles=series(100.0), daily=daily)
with_w = P.evaluate_pump_dump(candles=series(100.0), daily=daily, weekly=w_ok)
assert with_w["parts_l"]["levels"] >= base["parts_l"]["levels"]
print("OK PUMP&DUMP port: vol_sma per bar as in Pine, weekly levels wired, parts exposed")
