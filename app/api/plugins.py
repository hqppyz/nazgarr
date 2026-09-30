"""Plugin caricati e adapter disponibili (docs/ROADMAP.md Fase 10): per
Settings > Plugins e per i form degli adapter. Sola lettura: la lista dei
plugin si cambia da NAZGARR_PLUGINS o data_dir/plugins.txt, con un riavvio."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_errors import coded_detail, from_coded_error
from app.deps import get_session
from app.plugins import REGISTRY
from app.plugins import config as plugin_config
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


# Gli adapter senza una riga propria: si configurano qui (tracker e client
# dei plugin si configurano sulla loro riga, con le loro API).
GLOBAL_KINDS = ("image_host", "media_resolver", "notification")


class AdapterConfigResponse(BaseModel):
    kind: str
    adapter_type: str
    enabled: bool
    values: dict
    secrets_set: list[str]


class AdapterConfigRequest(BaseModel):
    enabled: bool | None = None
    config: dict | None = None  # un segreto assente o null resta com'era, "" lo cancella


def _global_spec(kind: str, adapter_type: str):
    spec = REGISTRY.get(kind, adapter_type)
    if kind not in GLOBAL_KINDS or spec is None or spec.plugin is None:
        raise HTTPException(status_code=404, detail=coded_detail("adapter_not_found", kind=kind, type=adapter_type))
    return spec


def _config_response(session: Session, spec) -> AdapterConfigResponse:
    row = plugin_config.global_config(session, spec.kind, spec.adapter_type)
    public = plugin_config.public(spec, plugin_config.loads(row.config_json) if row else None)
    return AdapterConfigResponse(kind=spec.kind, adapter_type=spec.adapter_type,
                                 enabled=row.enabled if row else True, **public)


@router.get("/config/{kind}/{adapter_type}", response_model=AdapterConfigResponse)
def get_adapter_config(kind: str, adapter_type: str, session: Session = Depends(get_session)):
    return _config_response(session, _global_spec(kind, adapter_type))


@router.put("/config/{kind}/{adapter_type}", response_model=AdapterConfigResponse)
def put_adapter_config(
    kind: str, adapter_type: str, body: AdapterConfigRequest, session: Session = Depends(get_session)
):
    spec = _global_spec(kind, adapter_type)
    try:
        plugin_config.save_global(session, spec, body.config, body.enabled)
    except plugin_config.AdapterConfigError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    return _config_response(session, spec)
