"""Цілі 2 і 3 за рівнями з індикатора власниці (ICT SMC HUNTER v9.9), без вигадування.

Pine: TP2 = максимум азійської сесії, інакше максимум попереднього дня; TP3 = максимум попереднього дня,
інакше тижневий максимум (для SHORT — мінімуми). Формульний запас «3R/5R» з Pine тут НЕ використовується:
немає реального рівня — пишемо «немає обґрунтованої цілі», а не заповнюємо шаблон.
Ціль 1 не змінюється (це рішення власниці про пороги). Лише інформація до плану; ордерів і гейтів немає.
Санітарний мінімум: ціль має бути далі за попередню щонайменше на чверть відстані до цілі 1.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

MIN_GAP_FRAC = 0.25
WHY = {"asia": "межа азійської сесії", "pd": "рівень попереднього дня", "week": "рівень попереднього тижня"}


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _prev(rows: Any, key: str, lookback_extreme: str) -> Optional[float]:
    """Значення попередньої ЗАВЕРШЕНОЇ свічки (остання в списку — поточна, що формується)."""
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    return _f((rows[-2] or {}).get(key))


def levels(*, m15: Any, daily: Any, weekly: Any) -> Dict[str, Optional[float]]:
    from office_ict_hunter import _asia_range
    from office_trade_steer import _bars

    ar = _asia_range(_bars(m15)) if m15 else {"high": None, "low": None}
    return {"asia_high": ar.get("high"), "asia_low": ar.get("low"), "pdh": _prev(daily, "high", "max"), "pdl": _prev(daily, "low", "min"),
            "w_high": _prev(weekly, "high", "max"), "w_low": _prev(weekly, "low", "min")}


def structural_targets(*, direction: str, entry: Any, tp1: Any, lv: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """{'tp2': {'price','why'}|None, 'tp3': ...|None}. Порядок кандидатів — як у Pine."""
    e, t1 = _f(entry), _f(tp1)
    out: Dict[str, Any] = {"tp2": None, "tp3": None}
    if e is None or t1 is None or t1 == e:
        return out
    long_ = str(direction or "").upper() != "SHORT"
    gap = abs(t1 - e) * MIN_GAP_FRAC
    sign = 1.0 if long_ else -1.0

    def beyond(price: Optional[float], base: float) -> bool:
        return price is not None and sign * (price - base) >= gap

    a, pd_, w = (lv.get("asia_high"), lv.get("pdh"), lv.get("w_high")) if long_ else (lv.get("asia_low"), lv.get("pdl"), lv.get("w_low"))
    cands2: List[tuple] = [("asia", a), ("pd", pd_)]
    for why, px in cands2:
        if beyond(px, t1):
            out["tp2"] = {"price": px, "why": WHY[why]}
            break
    base3 = out["tp2"]["price"] if out["tp2"] else t1
    for why, px in (("pd", pd_), ("week", w)):
        if beyond(px, base3):
            out["tp3"] = {"price": px, "why": WHY[why]}
            break
    return out
