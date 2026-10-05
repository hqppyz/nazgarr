"""Plugin caricati e adapter disponibili (docs/ROADMAP.md Fase 10): per
Settings > Plugins e per i form degli adapter. Sola lettura: la lista dei
plugin si cambia da NAZGARR_PLUGINS o data_dir/plugins.txt, con un riavvio."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.core import events
from nazgarr.core.errors import coded_detail, from_coded_error
from nazgarr.core.models import EventDelivery
from nazgarr.integrations import notifications, webhooks
from nazgarr.plugins import REGISTRY
from nazgarr.plugins import config as plugin_config
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


class LastDelivery(BaseModel):
    event: str
    status: str
    error: str | None
    at: datetime


class AdapterConfigResponse(BaseModel):
    kind: str
    adapter_type: str
    enabled: bool
    values: dict
    secrets_set: list[str]
    events: list[str] | None = None  # solo le notifiche: gli eventi che manda ("*" = tutti)
    last_delivery: LastDelivery | None = None  # solo le notifiche


class AdapterConfigRequest(BaseModel):
    enabled: bool | None = None
    config: dict | None = None  # un segreto assente o null resta com'era, "" lo cancella
    events: list[str] | None = None  # solo le notifiche


# Degli adapter integrati si configurano qui solo le notifiche (Discord,
# Telegram): gli image host integrati hanno le loro impostazioni nell'upload.
BUILTIN_CONFIGURABLE = ("notification",)


def _global_spec(kind: str, adapter_type: str):
    spec = REGISTRY.get(kind, adapter_type)
    if (kind not in GLOBAL_KINDS or spec is None
            or (spec.plugin is None and kind not in BUILTIN_CONFIGURABLE)):
        raise HTTPException(status_code=404, detail=coded_detail("adapter_not_found", kind=kind, type=adapter_type))
    return spec


def _config_response(session: Session, spec) -> AdapterConfigResponse:
    row = plugin_config.global_config(session, spec.kind, spec.adapter_type)
    public = plugin_config.public(spec, plugin_config.loads(row.config_json) if row else None)
    extra: dict = {}
    if spec.kind == "notification":
        extra["events"] = notifications.subscribed_events(session, spec.adapter_type)
        last = (session.query(EventDelivery).filter_by(notification_type=spec.adapter_type)
                .order_by(EventDelivery.id.desc()).first())
        if last is not None:
            extra["last_delivery"] = LastDelivery(event=last.event.name, status=last.status, error=last.last_error,
                                                  at=last.delivered_at or last.created_at)
    return AdapterConfigResponse(kind=spec.kind, adapter_type=spec.adapter_type,
                                 enabled=row.enabled if row else True, **public, **extra)


@router.get("/config/{kind}/{adapter_type}", response_model=AdapterConfigResponse)
def get_adapter_config(kind: str, adapter_type: str, session: Session = Depends(get_session)):
    return _config_response(session, _global_spec(kind, adapter_type))


@router.put("/config/{kind}/{adapter_type}", response_model=AdapterConfigResponse)
def put_adapter_config(
    kind: str, adapter_type: str, body: AdapterConfigRequest, session: Session = Depends(get_session)
):
    spec = _global_spec(kind, adapter_type)
    try:
        row = plugin_config.save_global(session, spec, body.config, body.enabled)
    except plugin_config.AdapterConfigError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    if body.events is not None and spec.kind == "notification":
        unknown = [e for e in body.events if e != events.ALL and e not in events.CATALOG]
        if unknown or not body.events:
            raise HTTPException(status_code=400, detail=coded_detail("webhook_event_unknown",
                                                                     event=unknown[0] if unknown else ""))
        row.events_json = json.dumps(sorted(set(body.events)))
        session.commit()
    return _config_response(session, spec)


class TestResponse(BaseModel):
    status: str
    error: str | None


@router.post("/config/notification/{adapter_type}/test", response_model=TestResponse)
def test_notification(adapter_type: str, session: Session = Depends(get_session)):
    """Una notifica di prova, mandata subito."""
    spec = _global_spec("notification", adapter_type)
    event = events.store(session, "test", {"message": "Hello from Nazgarr"}, only_notification=spec.adapter_type)
    session.commit()
    delivery = event.deliveries[0]
    webhooks.attempt(session, delivery, client=None)
    return TestResponse(status=delivery.status, error=delivery.last_error)
