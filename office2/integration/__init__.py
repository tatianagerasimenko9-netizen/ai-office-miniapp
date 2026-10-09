"""Read-only контракти єдиного Office для Brain і shadow-методик."""

from office2.integration.adapters import from_brain, from_gerchik, from_smc
from office2.integration.contract import validate_observation
from office2.integration.gerchik_inventory import gerchik_scenario_inventory
from office2.integration.shadow_compare import compare_shadow

__all__ = ["compare_shadow", "from_brain", "from_gerchik", "from_smc", "gerchik_scenario_inventory", "validate_observation"]
