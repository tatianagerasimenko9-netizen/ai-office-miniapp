"""Перевірений проти коду інвентар п'яти базових сценаріїв Gerchik.

Оригінального PDF/EPUB у репозиторії немає. Тому жодна реалізація не
позначається як підтверджена першоджерелом, навіть якщо конспект називає її
«шаром А».
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

_SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "GERCHIK-BOUNCE",
        "name_ua": "відбій від рівня",
        "implementation_status": "DOCS_ONLY",
        "primary_source_status": "SOURCE_UNAVAILABLE",
        "code": [],
        "related_code": ["office_level_scalp:setup=bounce", "office2.brain2:M15 trigger", "office2.evidence.mirror_level"],
        "tests": [],
        "gap": "немає окремого детектора БСУ/БПУ1/БПУ2, вирівнювання, поджаття і недобою; найближчі аналоги не є Gerchik-08",
        "office2_ready_impact": "NONE_AS_GERCHIK_MODEL",
        "legacy_impact": "PROMPT_AND_ANALOG_ONLY",
    },
    {
        "id": "GERCHIK-BREAKOUT",
        "name_ua": "пробій рівня",
        "implementation_status": "DOCS_ONLY",
        "primary_source_status": "SOURCE_UNAVAILABLE",
        "code": [],
        "related_code": ["office_levels.events:level_hold/level_retest", "office2.brain:pullback_break", "office2.smc.liquidity:ACCEPTED_BREAKOUT"],
        "tests": [],
        "gap": "немає окремої класифікації поджаття малими барами та імпульсу 2–3×; generic hold/retest і Brain sequence не є Gerchik-09",
        "office2_ready_impact": "NONE_AS_GERCHIK_MODEL",
        "legacy_impact": "PROMPT_AND_ANALOG_ONLY",
    },
    {
        "id": "GERCHIK-FALSE-BREAK-1BAR",
        "name_ua": "однобарний хибний пробій",
        "implementation_status": "PARTIAL",
        "primary_source_status": "SOURCE_UNAVAILABLE",
        "code": ["office_levels.events:level_false_break"],
        "tests": ["scripts/test_levels.py"],
        "gap": "внутрішня геометрія wick ≥0.1 ATR + close назад лише на останньому барі; немає окремого 1BAR label, перевірки відсутності імпульсу, D1 і cap ≤1/3 ATR",
        "office2_ready_impact": "NONE",
        "legacy_impact": "LTF_CONFIRM_AND_LAYER_B_SCORE",
    },
    {
        "id": "GERCHIK-FALSE-BREAK-2BAR",
        "name_ua": "двобарний хибний пробій",
        "implementation_status": "PARTIAL",
        "primary_source_status": "SOURCE_UNAVAILABLE",
        "code": ["office2.pipeline._events:type B"],
        "related_shadow_code": ["office2.smc.liquidity:FRESH_RAID", "office2.scenarios.pierces:B1"],
        "tests": ["scripts/test_office2.py", "scripts/test_smc_liquidity.py"],
        "gap": "reclaim window є untyped event/shadow analog; немає окремого Gerchik classifier та правила другого close за рівнем",
        "office2_ready_impact": "UNTYPED_SWEEP_EVENT_NOT_GERCHIK_MODEL",
        "legacy_impact": "NONE",
    },
    {
        "id": "GERCHIK-FALSE-BREAK-COMPLEX",
        "name_ua": "складний хибний пробій",
        "implementation_status": "DOCS_ONLY",
        "primary_source_status": "SOURCE_UNAVAILABLE",
        "code": [],
        "related_shadow_code": ["office2.smc.liquidity:ACCEPTED_BREAKOUT/LATE_SWEEP"],
        "tests": [],
        "gap": "немає Gerchik state machine для 3+ барів у зоні пробою, повернення, інвалідації та entry geometry; ACCEPTED_BREAKOUT трактує цю геометрію як acceptance",
        "office2_ready_impact": "NONE",
        "legacy_impact": "NONE",
    },
]


def gerchik_scenario_inventory() -> List[Dict[str, Any]]:
    """Повертає копію, щоб звіт не міг змінити канонічний інвентар."""
    return deepcopy(_SCENARIOS)
