"""Plugin e registro degli adapter (docs/ROADMAP.md Fase 10). Gli adapter
integrati si registrano al primo uso del registro (Registry._ensure_builtins)."""

from nazgarr.plugins.registry import REGISTRY, AdapterContext, AdapterSpec, ConfigField, register

__all__ = ["REGISTRY", "AdapterContext", "AdapterSpec", "ConfigField", "register"]
