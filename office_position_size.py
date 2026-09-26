"""Розмір позиції: ризик 1% депо (2% якщо score ≥ поріг+4). Не ордер.

Депо: OFFICE_DEPO_USDT. Немає — лише відсоток ризику, без USDT.
Не змінює ATR 80/90, Edge 85, MIN_RR 1.5.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


RISK_PCT_BASE = 0.01
RISK_PCT_STRONG = 0.02
SCORE_STRONG_EXTRA = 4
DEPO_ENV = "OFFICE_DEPO_USDT"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x <= 0:
        return None
    return x


def depo_usdt() -> Optional[float]:
    return _f(os.getenv(DEPO_ENV))


def risk_pct_for_score(score: Any, min_score: Any) -> float:
    sc, mn = _f(score), _f(min_score)
    if sc is not None and mn is not None and sc + 1e-12 >= mn + SCORE_STRONG_EXTRA:
        return RISK_PCT_STRONG
    return RISK_PCT_BASE


def plan_position_size(
    *,
    entry: Any,
    sl: Any,
    score: Any = None,
    min_score: Any = 8,
    depo: Any = None,
) -> Dict[str, Any]:
    """Кількість USDT = ризик$ ÷ (відстань до стопа в частках ціни)."""
    e, s = _f(entry), _f(sl)
    empty = {
        "ok": False,
        "risk_pct": RISK_PCT_BASE,
        "stop_pct": None,
        "size_usdt": None,
        "line": "",
    }
    if e is None or s is None or e == s:
        return empty
    stop_frac = abs(e - s) / e
    stop_pct = stop_frac * 100.0
    rp = risk_pct_for_score(score, min_score)
    dep = _f(depo) if depo is not None else depo_usdt()
    size = None
    if dep is not None and stop_frac > 0:
        size = dep * rp / stop_frac
    if size is not None:
        line = f"Розмір: {size:.2f} USDT (ризик {rp * 100:.0f}% · стоп {stop_pct:.2f}%)"
    else:
        line = f"Розмір: ризик {rp * 100:.0f}% депо · стоп {stop_pct:.2f}%"
    return {
        "ok": True,
        "risk_pct": rp,
        "stop_pct": stop_pct,
        "size_usdt": size,
        "depo": dep,
        "line": line,
    }
