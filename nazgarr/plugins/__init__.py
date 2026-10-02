"""Plugin e registro degli adapter (docs/ROADMAP.md Fase 10). Importare il
pacchetto registra gli adapter integrati."""

from nazgarr.plugins import builtin  # noqa: F401  (registra gli adapter integrati)
from nazgarr.plugins.registry import REGISTRY, AdapterContext, AdapterSpec, ConfigField, register

__all__ = ["REGISTRY", "AdapterContext", "AdapterSpec", "ConfigField", "register"]
