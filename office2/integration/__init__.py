"""Read-only контракти єдиного Office для Brain і shadow-методик."""

from office2.integration.adapters import from_brain, from_gerchik, from_gerchik_scenario, from_smc
from office2.integration.contract import validate_observation
from office2.integration.gerchik_inventory import gerchik_scenario_inventory
from office2.integration.gerchik_source_rules import (
    SOURCE_ID,
    SOURCE_PARTS,
    SOURCE_SHA256,
    gerchik_source_rules,
    validate_source_registry,
)
from office2.integration.gerchik_scenarios import SCENARIOS, ShadowParams, detect_gerchik_scenarios
from office2.integration.shadow_compare import compare_shadow

__all__ = [
    "SOURCE_ID",
    "SOURCE_PARTS",
    "SOURCE_SHA256",
    "compare_shadow",
    "from_brain",
    "from_gerchik",
    "from_gerchik_scenario",
    "from_smc",
    "gerchik_scenario_inventory",
    "gerchik_source_rules",
    "validate_observation",
    "validate_source_registry",
    "SCENARIOS",
    "ShadowParams",
    "detect_gerchik_scenarios",
]
