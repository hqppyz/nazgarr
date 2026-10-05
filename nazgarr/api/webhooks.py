"""Webhook (nazgarr/integrations/webhooks.py, nazgarr/core/events.py): configurazione, storico delle
consegne e invio di prova. Il segreto per la firma si vede una volta, alla
creazione o quando lo si rigenera."""

import json
import secrets
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.core import events, net_guard
from nazgarr.core.errors import coded_detail
from nazgarr.core.models import EventDelivery, Webhook
from nazgarr.integrations import webhooks
from nazgarr.web.deps import get_session

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class EventInfo(BaseModel):
    name: str
    description: str


class WebhookResponse(BaseModel):
    id: int
    name: str
    url: str
    events: list[str]
    enabled: bool
    created_at: datetime
    last_status: str | None = None  # l'ultima consegna: delivered | failed | pending
    last_delivery_at: datetime | None = None


class WebhookWithSecret(WebhookResponse):
    secret: str  # l'unica volta che si vede


class WebhookRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    events: list[str] | None = None
    enabled: bool | None = None


class DeliveryResponse(BaseModel):
    id: int
    event_id: int
    event: str
    status: str
    attempts: int
    next_attempt_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime


def _response(session: Session, webhook: Webhook) -> WebhookResponse:
    last = (session.query(EventDelivery).filter_by(webhook_id=webhook.id)
            .order_by(EventDelivery.id.desc()).first())
    return WebhookResponse(
        id=webhook.id, name=webhook.name, url=webhook.url, events=json.loads(webhook.events_json),
        enabled=webhook.enabled, created_at=webhook.created_at,
        last_status=last.status if last else None,
        last_delivery_at=(last.delivered_at or last.created_at) if last else None,
    )


def _events(names: list[str]) -> list[str]:
    unknown = [n for n in names if n != events.ALL and n not in events.CATALOG]
    if unknown:
        raise HTTPException(status_code=400, detail=coded_detail("webhook_event_unknown", event=unknown[0]))
    if not names:
        raise HTTPException(status_code=400, detail=coded_detail("webhook_events_required"))
    return sorted(set(names))


def _url(url: str) -> str:
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail=coded_detail("webhook_url_invalid"))
    try:
        net_guard.check_url(url)  # mai i metadati del cloud o un link-local
    except net_guard.ForbiddenDestination as exc:
        raise HTTPException(status_code=400, detail=coded_detail("webhook_url_invalid")) from exc
    return url


def _get(session: Session, webhook_id: int) -> Webhook:
    webhook = session.get(Webhook, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=404, detail=coded_detail("webhook_not_found", id=webhook_id))
    return webhook


@router.get("/events", response_model=list[EventInfo])
def list_events():
    return [EventInfo(name=name, description=text) for name, text in events.CATALOG.items() if name != "test"]


@router.get("", response_model=list[WebhookResponse])
def list_webhooks(session: Session = Depends(get_session)):
    return [_response(session, w) for w in session.query(Webhook).order_by(Webhook.id)]


@router.post("", response_model=WebhookWithSecret, status_code=201)
def create_webhook(body: WebhookRequest, session: Session = Depends(get_session)):
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail=coded_detail("webhook_name_required"))
    secret = secrets.token_hex(32)
    webhook = Webhook(name=body.name.strip(), url=_url(body.url or ""), secret=secret,
                      events_json=json.dumps(_events(body.events or [])), enabled=body.enabled is not False)
    session.add(webhook)
    session.commit()
    return WebhookWithSecret(**_response(session, webhook).model_dump(), secret=secret)


@router.patch("/{webhook_id}", response_model=WebhookResponse)
def update_webhook(webhook_id: int, body: WebhookRequest, session: Session = Depends(get_session)):
    webhook = _get(session, webhook_id)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail=coded_detail("webhook_name_required"))
        webhook.name = body.name.strip()
    if body.url is not None:
        webhook.url = _url(body.url)
    if body.events is not None:
        webhook.events_json = json.dumps(_events(body.events))
    if body.enabled is not None:
        webhook.enabled = body.enabled
    session.commit()
    return _response(session, webhook)


@router.post("/{webhook_id}/rotate-secret", response_model=WebhookWithSecret)
def rotate_secret(webhook_id: int, session: Session = Depends(get_session)):
    webhook = _get(session, webhook_id)
    webhook.secret = secrets.token_hex(32)
    session.commit()
    return WebhookWithSecret(**_response(session, webhook).model_dump(), secret=webhook.secret)


@router.delete("/{webhook_id}", status_code=204)
def delete_webhook(webhook_id: int, session: Session = Depends(get_session)):
    session.delete(_get(session, webhook_id))
    session.commit()


@router.get("/{webhook_id}/deliveries", response_model=list[DeliveryResponse])
def list_deliveries(webhook_id: int, session: Session = Depends(get_session)):
    _get(session, webhook_id)
    rows = (session.query(EventDelivery).filter_by(webhook_id=webhook_id)
            .order_by(EventDelivery.id.desc()).limit(50).all())
    return [
        DeliveryResponse(
            id=d.id, event_id=d.event_id, event=d.event.name, status=d.status, attempts=d.attempts,
            next_attempt_at=d.next_attempt_at, last_status_code=d.last_status_code, last_error=d.last_error,
            delivered_at=d.delivered_at, created_at=d.created_at,
        )
        for d in rows
    ]


@router.post("/{webhook_id}/test", response_model=DeliveryResponse)
def send_test(webhook_id: int, session: Session = Depends(get_session)):
    """Un evento "test" solo per questo webhook, consegnato subito."""
    webhook = _get(session, webhook_id)
    event = events.store(session, "test", {"message": "Hello from Nazgarr", "webhook": webhook.name},
                         only_webhook_id=webhook.id)
    session.commit()
    delivery = event.deliveries[0]
    with httpx.Client(follow_redirects=False) as client:
        webhooks.attempt(session, delivery, client)
    return list_deliveries(webhook_id, session)[0]
