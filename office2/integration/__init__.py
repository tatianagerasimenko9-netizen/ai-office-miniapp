"""Read-only контракти єдиного Office для Brain і shadow-методик."""

from office2.integration.adapters import from_brain, from_gerchik, from_smc
from office2.integration.contract import validate_observation

__all__ = ["from_brain", "from_gerchik", "from_smc", "validate_observation"]
