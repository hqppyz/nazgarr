"""Plugin caricati e adapter disponibili (docs/ROADMAP.md Fase 10): per
Settings > Plugins e per i form degli adapter. Sola lettura: la lista dei
plugin si cambia da NAZGARR_PLUGINS o data_dir/plugins.txt, con un riavvio."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.plugins import REGISTRY
from app.plugins.loader import ENV_VAR, STATE
from nazgarr_sdk import SDK_VERSION

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class ConfigFieldResponse(BaseModel):
    key: str
    label: str
    type: str
    required: bool
    default: str | int | float | bool | None = None
    help: str | None = None
    choices: list[str] = []


class AdapterResponse(BaseModel):
    kind: str
    adapter_type: str
    label: str
    description: str | None
    plugin: str | None  # None = integrato
    config_fields: list[ConfigFieldResponse]


class PluginResponse(BaseModel):
    name: str
    distribution: str | None
    version: str | None
    status: str
    error: str | None
    requires_sdk: str | None
    adapters: list[str]


class PluginsResponse(BaseModel):
    sdk_version: str
    env_var: str
    source: str | None
    requested: list[str]
    install_error: str | None
    plugins: list[PluginResponse]
    adapters: list[AdapterResponse]


def _adapter(spec) -> AdapterResponse:
    return AdapterResponse(
        kind=spec.kind, adapter_type=spec.adapter_type, label=spec.label, description=spec.description,
        plugin=spec.plugin,
        config_fields=[
            ConfigFieldResponse(key=f.key, label=f.label, type=f.type, required=f.required, default=f.default,
                                help=f.help, choices=list(f.choices))
            for f in spec.config_fields
        ],
    )


@router.get("", response_model=PluginsResponse)
def list_plugins():
    specs = sorted(REGISTRY.all(), key=lambda s: (s.kind, s.plugin is not None, s.label.lower()))
    return PluginsResponse(
        sdk_version=SDK_VERSION, env_var=ENV_VAR, source=STATE.source, requested=STATE.requested,
        install_error=STATE.install_error,
        plugins=[PluginResponse(**vars(p)) for p in STATE.plugins],
        adapters=[_adapter(spec) for spec in specs],
    )
