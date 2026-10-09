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
        "implementation_status": "PARTIAL",
        "primary_source_status": "SOURCE_UNAVAILABLE",
        "code": ["office_levels.events:level_hold/level_retest", "office2.evidence.mirror_level"],
        "tests": ["scripts/test_levels.py", "scripts/test_office2_brain2.py"],
        "gap": "немає окремого детектора БСУ/БПУ1/БПУ2, вирівнювання і недобою; Office2 mirror є evidence-only",
        "office2_ready_impact": "NONE",
        "legacy_impact": "LTF_CONFIRM_CONTEXT",
    },
    {
        "id": "GERCHIK-BREAKOUT",
        "name_ua": "пробій рівня",
        "implementation_status": "PARTIAL",
        "primary_source_status": "SOURCE_UNAVAILABLE",
        "code": ["office_levels.events:level_hold/level_retest", "office2.brain2:PULLBACK_BREAK"],
        "tests": ["scripts/test_levels.py", "scripts/test_office2_brain2.py"],
        "gap": "немає окремої Gerchik-класифікації поджаття, малих барів та авторського імпульсу; Brain sequence є власною моделлю",
        "office2_ready_impact": "GENERIC_BRAIN_SEQUENCE_NOT_GERCHIK_ENGINE",
        "legacy_impact": "LTF_CONFIRM_CONTEXT",
    },
    {
        "id": "GERCHIK-FALSE-BREAK-1BAR",
        "name_ua": "однобарний хибний пробій",
        "implementation_status": "IMPLEMENTED_INTERNAL",
        "primary_source_status": "SOURCE_UNAVAILABLE",
        "code": ["office_levels.events:level_false_break"],
        "tests": ["scripts/test_levels.py"],
        "gap": "реалізовано внутрішню геометрію wick ≥0.1 ATR + close назад лише на останньому закритому барі; fidelity до книги не перевірена",
        "office2_ready_impact": "NONE",
        "legacy_impact": "LTF_CONFIRM_AND_LAYER_B_SCORE",
    },
    {
        "id": "GERCHIK-FALSE-BREAK-2BAR",
        "name_ua": "двобарний хибний пробій",
        "implementation_status": "NOT_IMPLEMENTED",
        "primary_source_status": "SOURCE_UNAVAILABLE",
        "code": [],
        "related_shadow_code": ["office2.smc.liquidity:FRESH_RAID"],
        "tests": [],
        "gap": "SMC two-bar reclaim не атрибутується Gerchik і не доводить модель «закриття за рівнем + повернення» за першоджерелом",
        "office2_ready_impact": "NONE",
        "legacy_impact": "NONE",
    },
    {
        "id": "GERCHIK-FALSE-BREAK-COMPLEX",
        "name_ua": "складний хибний пробій",
        "implementation_status": "NOT_IMPLEMENTED",
        "primary_source_status": "SOURCE_UNAVAILABLE",
        "code": [],
        "related_shadow_code": ["office2.smc.liquidity:ACCEPTED_BREAKOUT/LATE_SWEEP"],
        "tests": [],
        "gap": "немає Gerchik state machine для 3+ барів за рівнем, повернення, інвалідації та entry geometry",
        "office2_ready_impact": "NONE",
        "legacy_impact": "NONE",
    },
]


def gerchik_scenario_inventory() -> List[Dict[str, Any]]:
    """Повертає копію, щоб звіт не міг змінити канонічний інвентар."""
    return deepcopy(_SCENARIOS)
