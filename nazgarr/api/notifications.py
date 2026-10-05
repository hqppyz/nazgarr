"""Servizi di notifica (nazgarr/integrations/notifications.py): istanze di un
adapter "notification" (Discord, Telegram, quelli dei plugin), quante se ne
vuole per tipo (decisione dell'utente, 2026-10-05). I campi di ogni tipo
sono i suoi ConfigField (/api/plugins); i segreti non tornano mai."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.api.webhooks import DeliveryResponse, delivery_response, validated_events
from nazgarr.core import events
from nazgarr.core.errors import coded_detail, from_coded_error
from nazgarr.core.models import EventDelivery, NotificationService
from nazgarr.integrations import notifications, webhooks
from nazgarr.plugins import REGISTRY
from nazgarr.plugins import config as plugin_config
from nazgarr.web.deps import get_session

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationServiceResponse(BaseModel):
    id: int
    name: str
    adapter_type: str
    available: bool  # False se il plugin che lo fornisce non c'è più
    enabled: bool
    values: dict  # i campi non segreti
    secrets_set: list[str]
    events: list[str]
    message_format: str
    created_at: datetime
    last_status: str | None = None  # l'ultima consegna: delivered | failed | pending
    last_error: str | None = None
    last_delivery_at: datetime | None = None


class NotificationServiceRequest(BaseModel):
    name: str | None = None
    adapter_type: str | None = None  # solo alla creazione
    enabled: bool | None = None
    config: dict | None = None  # un segreto assente o null resta com'era, "" lo cancella
    events: list[str] | None = None
    message_format: str | None = None


class NotificationTestRequest(BaseModel):
    """Una prova prima di salvare: i valori del form; con service_id, i
    segreti non reinviati sono quelli già salvati di quel servizio."""

    adapter_type: str
    config: dict | None = None
    service_id: int | None = None


class NotificationTestResponse(BaseModel):
    status: str  # delivered | failed
    error: str | None


def _spec(adapter_type: str | None):
    spec = REGISTRY.get("notification", adapter_type)
    if spec is None:
        raise HTTPException(status_code=400, detail=coded_detail("notification_type_unknown", type=adapter_type or ""))
    return spec


def _get(session: Session, service_id: int) -> NotificationService:
    service = session.get(NotificationService, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail=coded_detail("notification_service_not_found", id=service_id))
    return service


def _name(name: str | None) -> str:
    if not (name or "").strip():
        raise HTTPException(status_code=400, detail=coded_detail("notification_name_required"))
    return name.strip()


def _format(value: str) -> str:
    if value not in notifications.FORMATS:
        raise HTTPException(status_code=400, detail=coded_detail("notification_format_unknown", format=value))
    return value


def _config(spec, incoming: dict | None, existing: dict | None) -> dict:
    try:
        return plugin_config.validate(spec, incoming, existing)
    except plugin_config.AdapterConfigError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc


def _response(session: Session, service: NotificationService) -> NotificationServiceResponse:
    spec = REGISTRY.get("notification", service.adapter_type)
    last = (session.query(EventDelivery).filter_by(notification_id=service.id)
            .order_by(EventDelivery.id.desc()).first())
    return NotificationServiceResponse(
        id=service.id, name=service.name, adapter_type=service.adapter_type, available=spec is not None,
        enabled=service.enabled, **plugin_config.public(spec, plugin_config.loads(service.config_json)),
        events=notifications.subscribed_events(service), message_format=service.message_format,
        created_at=service.created_at,
        last_status=last.status if last else None, last_error=last.last_error if last else None,
        last_delivery_at=(last.delivered_at or last.created_at) if last else None,
    )


@router.get("", response_model=list[NotificationServiceResponse])
def list_services(session: Session = Depends(get_session)):
    return [_response(session, s) for s in session.query(NotificationService).order_by(NotificationService.id)]


@router.post("", response_model=NotificationServiceResponse, status_code=201)
def create_service(body: NotificationServiceRequest, session: Session = Depends(get_session)):
    spec = _spec(body.adapter_type)
    service = NotificationService(
        name=_name(body.name), adapter_type=spec.adapter_type, enabled=body.enabled is not False,
        config_json=plugin_config.dumps(_config(spec, body.config, None)),
        events_json=json.dumps(validated_events(body.events if body.events is not None else [events.ALL])),
        message_format=_format(body.message_format or notifications.DEFAULT_FORMAT),
    )
    session.add(service)
    session.commit()
    return _response(session, service)


@router.patch("/{service_id}", response_model=NotificationServiceResponse)
def update_service(service_id: int, body: NotificationServiceRequest, session: Session = Depends(get_session)):
    service = _get(session, service_id)
    if body.adapter_type is not None and body.adapter_type != service.adapter_type:
        raise HTTPException(status_code=400, detail=coded_detail("notification_type_immutable"))
    if body.name is not None:
        service.name = _name(body.name)
    if body.config is not None:
        service.config_json = plugin_config.dumps(
            _config(_spec(service.adapter_type), body.config, plugin_config.loads(service.config_json))
        )
    if body.events is not None:
        service.events_json = json.dumps(validated_events(body.events))
    if body.message_format is not None:
        service.message_format = _format(body.message_format)
    if body.enabled is not None:
        service.enabled = body.enabled
    session.commit()
    return _response(session, service)


@router.delete("/{service_id}", status_code=204)
def delete_service(service_id: int, session: Session = Depends(get_session)):
    """Con il servizio se ne vanno anche le sue consegne, in coda o no."""
    service = _get(session, service_id)
    session.query(EventDelivery).filter_by(notification_id=service.id).delete(synchronize_session=False)
    session.delete(service)
    session.commit()


@router.get("/{service_id}/deliveries", response_model=list[DeliveryResponse])
def list_deliveries(service_id: int, session: Session = Depends(get_session)):
    _get(session, service_id)
    rows = (session.query(EventDelivery).filter_by(notification_id=service_id)
            .order_by(EventDelivery.id.desc()).limit(50).all())
    return [delivery_response(d) for d in rows]


@router.post("/{service_id}/test", response_model=NotificationTestResponse)
def test_service(service_id: int, session: Session = Depends(get_session)):
    """Una notifica di prova al servizio salvato, mandata subito e tenuta
    nello storico delle sue consegne."""
    service = _get(session, service_id)
    event = events.store(session, "test", {"message": "Hello from Nazgarr", "service": service.name},
                         only_notification_id=service.id)
    session.commit()
    delivery = event.deliveries[0]
    webhooks.attempt(session, delivery, client=None)
    return NotificationTestResponse(status=delivery.status, error=delivery.last_error)


@router.post("/test", response_model=NotificationTestResponse)
def test_unsaved(body: NotificationTestRequest, session: Session = Depends(get_session)):
    """La prova dalla modale, con i valori non ancora salvati: non passa
    dalla coda e non lascia tracce."""
    spec = _spec(body.adapter_type)
    existing = None
    if body.service_id is not None:
        service = _get(session, body.service_id)
        if service.adapter_type != spec.adapter_type:
            raise HTTPException(status_code=400, detail=coded_detail("notification_type_immutable"))
        existing = plugin_config.loads(service.config_json)
    config = plugin_config.with_defaults(spec, _config(spec, body.config, existing))
    try:
        notifications.send(spec.adapter_type, config,
                           notifications.render("test", {"message": "Hello from Nazgarr"}), session)
    except Exception as exc:
        return NotificationTestResponse(status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
    return NotificationTestResponse(status="delivered", error=None)
