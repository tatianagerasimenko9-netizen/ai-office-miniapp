#!/usr/bin/env python3
"""Market regime v1 on synthetic OHLCV: trend, range, compression, expansion, unknown. Offline."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office_market_regime import MIN_BARS, classify_regime  # noqa: E402


def bars(closes, rng=None):
    out = []
    for i, c in enumerate(closes):
        r = rng(i) if rng else 0.5
        out.append({"open": c, "high": c + r, "low": c - r, "close": c, "ts": f"2026-09-{1 + i // 24:02d}T{i % 24:02d}:00:00+00:00"})
    return out


n = 60
trend = classify_regime(bars([100 + i * 0.8 + math.sin(i) * 0.3 for i in range(n)]))
assert trend["regime"] == "TREND" and trend["direction"] == "UP", trend
down = classify_regime(bars([200 - i * 0.8 + math.sin(i) * 0.3 for i in range(n)]))
assert down["regime"] == "TREND" and down["direction"] == "DOWN", down
rng = classify_regime(bars([100 + math.sin(i / 2) * 3 for i in range(n)]))
assert rng["regime"] == "RANGE", rng
comp_closes = [100 + math.sin(i / 2) * 3 if i < n - 14 else 100.0 + (i % 2) * 0.02 for i in range(n)]
comp = classify_regime(bars(comp_closes, rng=lambda i: 0.05 if i >= n - 14 else 2.0))
assert comp["regime"] == "COMPRESSION", comp
exp = classify_regime(bars([100 + math.sin(i / 2) * 3 for i in range(n)], rng=lambda i: 12.0 if i == n - 1 else 1.0))
assert exp["regime"] == "EXPANSION", exp
short = classify_regime(bars([100.0] * (MIN_BARS - 1)))
assert short["regime"] == "UNKNOWN" and short["data_status"] == "DATA_UNAVAILABLE"
broken = bars([100 + i for i in range(n)])
broken[10]["high"] = None
assert classify_regime(broken)["regime"] == "UNKNOWN", "gaps are not guessed"
assert all(r["order_authorized"] is False for r in (trend, rng, comp, exp, short))
print("OK market regime v1: trend up/down, range, compression, expansion, unknown on short/broken data")
