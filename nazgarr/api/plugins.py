"""Plugin caricati e adapter disponibili (docs/ROADMAP.md Fase 10): per
Settings > Plugins e per i form degli adapter. Sola lettura: la lista dei
plugin si cambia da NAZGARR_PLUGINS o data_dir/plugins.txt, con un riavvio."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.core.errors import coded_detail, from_coded_error
from nazgarr.core.version import __version__
from nazgarr.plugins import REGISTRY, switch
from nazgarr.plugins import config as plugin_config
from nazgarr.plugins.builtin import BUNDLED
from nazgarr.plugins.loader import ENV_VAR, STATE
from nazgarr.sdk import SDK_VERSION
from nazgarr.web.deps import get_session

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
    bundled: bool = False  # di un plugin incluso in Nazgarr (nazgarr/bundled)
    config_fields: list[ConfigFieldResponse]
    icon: str | None = None  # un'immagine data: dichiarata dal plugin (gli integrati hanno la loro nella UI)


class PluginResponse(BaseModel):
    name: str  # il nome con cui si registra (il pacchetto, per uno installato)
    label: str  # come si chiama nella UI: l'adapter, se ne ha uno solo
    distribution: str | None
    version: str | None
    status: str  # loaded | disabled | failed | incompatible
    error: str | None
    requires_sdk: str | None
    adapters: list[str]
    bundled: bool = False  # nativo, incluso in Nazgarr, non installato con pip
    enabled: bool = True
    description: str | None = None
    categories: list[str] = []  # i kind dei suoi adapter, per raggruppare
    settings: list[str] = []  # gli adapter con una configurazione propria qui: "kind:adapter_type"
    icon: str | None = None


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
        plugin=spec.plugin, bundled=spec.plugin in BUNDLED, icon=spec.icon,
        config_fields=[
            ConfigFieldResponse(key=f.key, label=f.label, type=f.type, required=f.required, default=f.default,
                                help=f.help, choices=list(f.choices))
            for f in spec.config_fields
        ],
    )


def _plugin(session: Session, off: set[str], **fields) -> PluginResponse:
    """Un plugin per la sua card: i suoi adapter (anche da spento), il nome
    da mostrare e cosa si configura qui (gli adapter globali con dei campi)."""
    owner = fields.get("distribution") or fields["name"]
    specs = switch.specs_of(owner)
    enabled = owner not in off
    status = fields.pop("status")
    if status == "loaded" and not enabled:
        status = "disabled"
    return PluginResponse(
        **fields, status=status, enabled=enabled,
        label=specs[0].label if len(specs) == 1 else owner,
        adapters=[f"{spec.kind}:{spec.adapter_type}" for spec in specs],
        categories=sorted({spec.kind for spec in specs}),
        settings=[f"{spec.kind}:{spec.adapter_type}" for spec in specs
                  if spec.kind in GLOBAL_KINDS and spec.config_fields],
        icon=next((spec.icon for spec in specs if spec.icon), None),
    )


@router.get("", response_model=PluginsResponse)
def list_plugins(session: Session = Depends(get_session)):
    off = switch.disabled(session)
    specs = sorted(REGISTRY.all(), key=lambda s: (s.kind, s.plugin is not None, s.label.lower()))
    return PluginsResponse(
        sdk_version=SDK_VERSION, env_var=ENV_VAR, source=STATE.source, requested=STATE.requested,
        install_error=STATE.install_error,
        plugins=[
            *(_plugin(session, off, name=name, distribution=None, version=__version__, status="loaded", error=None,
                      requires_sdk=module.REQUIRES_SDK, bundled=True, description=module.DESCRIPTION)
              for name, module in BUNDLED.items()),
            *(_plugin(session, off, **{k: v for k, v in vars(p).items() if k != "adapters"}) for p in STATE.plugins),
        ],
        adapters=[_adapter(spec) for spec in specs],
    )


# Gli adapter dei plugin senza una riga propria: si configurano qui (tracker
# e client dei plugin si configurano sulla loro riga, con le loro API; i
# servizi di notifica, integrati o dei plugin, da /api/notifications, perché
# ce ne può essere più di uno per tipo). Gli image host integrati hanno le
# loro impostazioni nell'upload.
GLOBAL_KINDS = ("image_host", "media_resolver")


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


class PluginEnabledRequest(BaseModel):
    enabled: bool


@router.put("/{name}/enabled", status_code=204)
def set_plugin_enabled(name: str, body: PluginEnabledRequest, session: Session = Depends(get_session)):
    """Accende o spegne un plugin, incluso o installato, senza riavviare."""
    try:
        switch.set_enabled(session, name, body.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=coded_detail("plugin_not_found", name=name)) from exc
