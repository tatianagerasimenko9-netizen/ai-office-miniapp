"""Фаза руху монети відносно напряму угоди: наскільки монета ВЖЕ пройшла в бік угоди (в одиницях σ). ІНФОРМАЦІЯ, не правило.

Виміри: рух за 30/60 хв ділимо на σ (стандартне відхилення 5m-змін за попередні 24 год × √(хв/5)). a>0 — монета вже рухалась у бік угоди, a<0 — проти.
Історичний довідник (scripts/phase_study.py, 63 ліквідні ф'ючерсні монети, 6 міс., 270 тис. входів у обидва боки, нейтральний результат: перший дотик ±1σ за годину
протягом 4 год; 50% = випадково; перевірочна частина збігається з навчальною): чим більше монета вже пройшла в бік угоди, тим гірше наступний результат,
особливо ≥3σ за 30 хв (SHORT 41,7%, LONG 46,6%). Входи проти імпульсу в середньому не гірші за випадкові. Це різниця у кілька п.п., а не прогноз.
Нічого не блокує й не змінює пороги."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

# межі a (σ за 30 хв) → фаза; відсотки — довідкові, з дослідження (SHORT/LONG, уся вибірка)
PHASES = (
    (-1e9, -0.5, "ще рано", "монета рухалась проти угоди", (52.0, 51.0)),
    (-0.5, 0.5, "формується", "монета майже не рухалась у бік угоди", (51.0, 49.0)),
    (0.5, 2.0, "рух пішов", "монета вже пройшла частину шляху", (49.5, 48.5)),
    (2.0, 3.0, "пізно", "монета вже пройшла багато", (48.5, 47.0)),
    (3.0, 1e9, "дуже пізно", "монета вже пройшла дуже багато", (41.7, 46.6)),
)


def _f(v: Any) -> Optional[float]:
    try:
        x = None if v is None else float(v)
    except (TypeError, ValueError):
        return None
    return None if x is None or x != x else x


def sigma_extension(closes: List[float], direction: str, minutes: int = 30, bar_min: int = 5) -> Optional[float]:
    """a — рух за `minutes` у бік угоди в σ; None, якщо замало даних (потрібно ≥ 24 год 5m-свічок)."""
    n = minutes // bar_min
    cs = [c for c in (_f(x) for x in closes) if c is not None]
    if len(cs) < 288 + n + 1:
        return None
    rets = [cs[i] / cs[i - 1] - 1.0 for i in range(len(cs) - 288, len(cs))]
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / len(rets))
    if sd <= 0:
        return None
    mv = cs[-1] / cs[-1 - n] - 1.0
    a = mv / (sd * math.sqrt(n))
    return round(a if str(direction).upper() != "SHORT" else -a, 2)


def phase_of(a: Optional[float], direction: str) -> Optional[Dict[str, Any]]:
    if a is None:
        return None
    short = str(direction).upper() == "SHORT"
    for lo, hi, name, why, hist in PHASES:
        if lo <= a < hi:
            return {"a30": a, "name": name, "why": why, "hist_win": hist[0] if short else hist[1]}
    return None


def line(ph: Optional[Dict[str, Any]]) -> str:
    """«Фаза руху: рух пішов — монета за 30 хв пройшла 1,2σ у бік угоди (історично такі входи вигравали ≈49% проти 50% випадково)»."""
    if not ph:
        return ""
    a = f"{abs(ph['a30']):.1f}".replace(".", ",")
    way = "у бік угоди" if ph["a30"] >= 0 else "проти угоди"
    return f"Фаза руху: {ph['name']} — монета за 30 хв пройшла {a}σ {way} (історично такі входи вигравали ≈{ph['hist_win']:.0f}% проти 50% випадково)"
