"""Інвентар п'яти сценаріїв: першоджерело окремо від executable-стану.

Приватний повний текст 2019 року перевірено, але не включено до Git.
Підтвердження правила джерелом не означає, що алгоритм уже реалізований.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

_SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "GERCHIK-BOUNCE",
        "name_ua": "відбій від рівня",
        "implementation_status": "SHADOW_EXECUTABLE",
        "primary_source_status": "PRIMARY_TEXT_VERIFIED",
        "source_rule_id": "GERCHIK-08-VIDBIY",
        "source_refs": ["P08:L127-L280", "P14:L372-L461"],
        "source_conditions": ["БСУ", "БПУ1", "сусідній БПУ2", "вирівнювальний бар за поджаття", "явне скасування"],
        "code": ["office2.integration.gerchik_scenarios:_bounce"],
        "related_code": ["office_level_scalp:setup=bounce", "office2.brain2:M15 trigger", "office2.evidence.mirror_level"],
        "tests": ["scripts/test_gerchik_scenarios.py"],
        "gap": "ATR-допуск «копійка в копійку» є shadow-операціоналізацією; pre-close limit entry у replay замінено рішенням після close",
        "office2_ready_impact": "NONE_AS_GERCHIK_MODEL",
        "legacy_impact": "PROMPT_AND_ANALOG_ONLY",
    },
    {
        "id": "GERCHIK-BREAKOUT",
        "name_ua": "пробій рівня",
        "implementation_status": "SHADOW_EXECUTABLE",
        "primary_source_status": "PRIMARY_TEXT_VERIFIED",
        "source_rule_id": "GERCHIK-09-PROBIY",
        "source_refs": ["P08:L346-L382", "P14:L489-L543"],
        "source_conditions": ["сильний рівень", "підхід малими барами або поджаттям", "імпульс після пробою", "явні entry і stop"],
        "code": ["office2.integration.gerchik_scenarios:_breakout"],
        "related_code": ["office_levels.events:level_hold/level_retest", "office2.brain:pullback_break", "office2.smc.liquidity:ACCEPTED_BREAKOUT"],
        "tests": ["scripts/test_gerchik_scenarios.py"],
        "gap": "small-bar та impulse ratios є явними shadow-параметрами; stop-order моделюється після закритого breakout-бара",
        "office2_ready_impact": "NONE_AS_GERCHIK_MODEL",
        "legacy_impact": "PROMPT_AND_ANALOG_ONLY",
    },
    {
        "id": "GERCHIK-FALSE-BREAK-1BAR",
        "name_ua": "однобарний хибний пробій",
        "implementation_status": "SHADOW_EXECUTABLE",
        "primary_source_status": "PRIMARY_TEXT_VERIFIED",
        "source_rule_id": "GERCHIK-06-LP-1BAR",
        "source_refs": ["P08:L505-L575", "P14:L619-L646", "P15:L4-L13"],
        "source_conditions": ["прокол і повернення одним баром", "entry до закриття", "stop за хвіст або рівень", "глибина близько 1/3 ATR", "TP ≥3R"],
        "code": ["office2.integration.gerchik_scenarios:_false_break_1bar"],
        "tests": ["scripts/test_gerchik_scenarios.py", "scripts/test_levels.py"],
        "gap": "pre-close order недоступний на закритих OHLCV; depth cap 0.30 від попереднього закритого D1 ATR перевіряється, але реакція інструмента на минулі пробої не має окремого feed",
        "office2_ready_impact": "NONE",
        "legacy_impact": "LTF_CONFIRM_AND_LAYER_B_SCORE",
    },
    {
        "id": "GERCHIK-FALSE-BREAK-2BAR",
        "name_ua": "двобарний хибний пробій",
        "implementation_status": "SHADOW_EXECUTABLE",
        "primary_source_status": "PRIMARY_TEXT_VERIFIED",
        "source_rule_id": "GERCHIK-06-LP-2BAR",
        "source_refs": ["P08:L616-L622", "P09:L1-L43", "P15:L23-L52"],
        "source_conditions": ["перший close за рівнем", "другий open за рівнем", "повернення другим баром", "entry-order після open", "TP ≥3R"],
        "code": ["office2.integration.gerchik_scenarios:_false_break_2bar"],
        "related_shadow_code": ["office2.smc.liquidity:FRESH_RAID", "office2.scenarios.pierces:B1"],
        "tests": ["scripts/test_gerchik_scenarios.py", "scripts/test_office2.py", "scripts/test_smc_liquidity.py"],
        "gap": "entry після open другого бара у replay виконується лише після його закритого підтвердження, щоб не допустити lookahead",
        "office2_ready_impact": "UNTYPED_SWEEP_EVENT_NOT_GERCHIK_MODEL",
        "legacy_impact": "NONE",
    },
    {
        "id": "GERCHIK-FALSE-BREAK-COMPLEX",
        "name_ua": "складний хибний пробій",
        "implementation_status": "SHADOW_EXECUTABLE",
        "primary_source_status": "PRIMARY_TEXT_VERIFIED",
        "source_rule_id": "GERCHIK-06-LP-COMPLEX",
        "source_refs": ["P09:L56-L139", "P15:L63-L99"],
        "source_conditions": ["щонайменше три бари у площині пробою", "без зворотного пробою до сетапу", "order на повернення", "технічний stop", "TP ≥3R"],
        "code": ["office2.integration.gerchik_scenarios:_false_break_complex"],
        "related_shadow_code": ["office2.smc.liquidity:ACCEPTED_BREAKOUT/LATE_SWEEP"],
        "tests": ["scripts/test_gerchik_scenarios.py", "scripts/test_smc_liquidity.py"],
        "gap": "окремий shadow-класифікатор навмисно не змінює SMC ACCEPTED_BREAKOUT і не створює READY",
        "office2_ready_impact": "NONE",
        "legacy_impact": "NONE",
    },
]


def gerchik_scenario_inventory() -> List[Dict[str, Any]]:
    """Повертає копію, щоб звіт не міг змінити канонічний інвентар."""
    return deepcopy(_SCENARIOS)
