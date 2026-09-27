"""Лінійний регресійний канал (портинг Pine LonesomeTheBlue).

Ліцензія оригіналу: Mozilla Public License 2.0
https://mozilla.org/MPL/2.0/
© LonesomeTheBlue — study «Linear Regression Channel».

Шар контексту і overlay графіка, не сигнал і не бал збігів. Closed-candle: остання незакрита
свічка не входить у розрахунок. Не змінює ATR/Edge/MIN_RR. Не ордер.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _src_close(rows: Sequence[Dict[str, Any]]) -> List[float]:
    out: List[float] = []
    for r in rows:
        x = _f(r.get("close") if isinstance(r, dict) else None)
        if x is None:
            return []
        out.append(x)
    return out


def linreg_value(src: Sequence[float], length: int, offset: int) -> Optional[float]:
    """Pine ta.linreg: OLS y = a + b*x, значення на offset від кінця вікна."""
    n = int(length)
    if n < 2 or len(src) < n + offset:
        return None
    window = list(src[-(n + offset) : len(src) - offset if offset else None])
    if len(window) != n:
        return None
    # x = 0..n-1
    sum_x = (n - 1) * n / 2.0
    sum_x2 = (n - 1) * n * (2 * n - 1) / 6.0
    sum_y = sum(window)
    sum_xy = sum(i * window[i] for i in range(n))
    den = n * sum_x2 - sum_x * sum_x
    if abs(den) < 1e-18:
        return None
    b = (n * sum_xy - sum_x * sum_y) / den
    a = (sum_y - b * sum_x) / n
    # Pine linreg(..., offset) — значення регресії на останній точці зсунутого вікна.
    return a + b * (n - 1)


def get_channel(src: Sequence[float], length: int) -> Optional[Tuple[float, float, float, float]]:
    """Як Pine get_channel: intercept, endy, dev, slope. src — закриті бари."""
    n = int(length)
    if n < 10 or len(src) < n:
        return None
    window = list(src[-n:])
    mid = sum(window) / n
    y0 = linreg_value(src, n, 0)
    y1 = linreg_value(src, n, 1)
    if y0 is None or y1 is None:
        return None
    slope = y0 - y1
    intercept = mid - slope * math.floor(n / 2) + ((1 - (n % 2)) / 2.0) * slope
    endy = intercept + slope * (n - 1)
    acc = 0.0
    for x in range(n):
        pred = slope * (n - 1 - x) + intercept
        # Pine: src[x] від кінця (x=0 — last of window)
        acc += (window[n - 1 - x] - pred) ** 2
    dev = math.sqrt(acc / n)
    return intercept, endy, dev, slope


def regression_channel(
    candles: Any,
    *,
    length: int = 100,
    deviation: float = 2.0,
    closed_only: bool = True,
) -> Dict[str, Any]:
    """Канал для контексту й overlay. Дотик до межі НЕ дає бал збігів і НЕ створює картку."""
    rows = [r for r in (candles or []) if isinstance(r, dict)]
    if closed_only and len(rows) >= 2:
        rows = rows[:-1]
    src = _src_close(rows)
    empty = {
        "ok": False,
        "data_status": "DATA_UNAVAILABLE",
        "signal": False,
        "confluence_tag": False,
        "creates_enter": False,
        "license": "MPL-2.0",
        "source": "LonesomeTheBlue Linear Regression Channel",
    }
    ch = get_channel(src, length)
    if not ch:
        return empty
    y1, y2, dev, slope = ch
    d = float(deviation)
    n = int(length)
    start_ts = rows[-n].get("ts") if len(rows) >= n else None
    end_ts = rows[-1].get("ts") if rows else None
    return {
        "ok": True,
        "data_status": "DATA_OK",
        "signal": False,
        "confluence_tag": False,
        "creates_enter": False,
        "license": "MPL-2.0",
        "source": "LonesomeTheBlue Linear Regression Channel",
        "length": n,
        "deviation": d,
        "slope": slope,
        "mid_start": y1,
        "mid_end": y2,
        "upper_start": y1 + dev * d,
        "upper_end": y2 + dev * d,
        "lower_start": y1 - dev * d,
        "lower_end": y2 - dev * d,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "closed_only": closed_only,
        "note": "контекст графіка, не вхід",
    }
