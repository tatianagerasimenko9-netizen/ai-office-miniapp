"""Торгова модель Price Action за видом тези Brain v2.1 (мітка для аналітики; на рішення не впливає).

REJECTION        — sweep/хибний пробій рівня з поверненням (SWEEP_SEQ, SWEEP_RECLAIM): відбій від зони.
BREAKOUT_RETEST  — пробій, закріплення й ретест (PULLBACK_BREAK).
ORIGIN_RETEST    — ретест зони походження імпульсу (ORIGIN_SEQ, ORIGIN_LOW).
Невідомий вид → UNKNOWN (не вгадуємо)."""
from typing import Optional

MODEL_BY_KIND = {"SWEEP_SEQ": "REJECTION", "SWEEP_RECLAIM": "REJECTION", "PULLBACK_BREAK": "BREAKOUT_RETEST", "ORIGIN_SEQ": "ORIGIN_RETEST", "ORIGIN_LOW": "ORIGIN_RETEST"}


def model_of(kind: Optional[str]) -> str:
    return MODEL_BY_KIND.get(str(kind or ""), "UNKNOWN")
