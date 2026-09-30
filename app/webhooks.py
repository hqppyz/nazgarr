"""Consegna dei webhook (docs/ROADMAP.md Fase 10, decisione dell'utente
2026-09-30: firmati, con ritentativi e uno storico delle consegne).

Ogni consegna è un POST JSON:

    {"id": <id evento>, "event": "seed_job.finished", "created_at": "...", "data": {...}}

con gli header
    X-Nazgarr-Event:     il nome dell'evento
    X-Nazgarr-Delivery:  l'id della consegna (lo stesso a ogni ritentativo)
    X-Nazgarr-Timestamp: secondi Unix dell'invio
    X-Nazgarr-Signature: sha256=<HMAC-SHA256 del segreto su "<timestamp>.<corpo>">

Chi riceve ricalcola la firma sul corpo così com'è arrivato e controlla che
il timestamp sia recente (niente replay). Una risposta 2xx è una consegna
riuscita; qualunque altra cosa si ritenta dopo 1 minuto, 5 minuti, 30
minuti, 2 ore e 6 ore, poi la consegna è fallita. Eventi e consegne restano
30 giorni.
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.models import Event, EventDelivery
from app.version import __version__

logger = logging.getLogger(__name__)

BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2), timedelta(hours=6))
MAX_ATTEMPTS = len(BACKOFF) + 1
TIMEOUT_SECONDS = 10.0
RETENTION = timedelta(days=30)
BATCH = 50


def signature(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def body_of(event: Event) -> bytes:
    created = event.created_at if event.created_at.tzinfo else event.created_at.replace(tzinfo=UTC)
    return json.dumps({
        "id": event.id, "event": event.name, "created_at": created.isoformat(),
        "data": json.loads(event.payload_json),
    }, separators=(",", ":")).encode()


def _send(client: httpx.Client, delivery: EventDelivery) -> tuple[bool, int | None, str | None]:
    webhook = delivery.webhook
    body = body_of(delivery.event)
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"Nazgarr/{__version__}",
        "X-Nazgarr-Event": delivery.event.name,
        "X-Nazgarr-Delivery": str(delivery.id),
        "X-Nazgarr-Timestamp": timestamp,
        "X-Nazgarr-Signature": signature(webhook.secret, timestamp, body),
    }
    try:
        response = client.post(webhook.url, content=body, headers=headers, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        return False, None, f"{type(exc).__name__}: {exc}"[:500]
    if 200 <= response.status_code < 300:
        return True, response.status_code, None
    return False, response.status_code, response.text[:500] or f"HTTP {response.status_code}"


def attempt(session: Session, delivery: EventDelivery, client: httpx.Client, now: datetime | None = None) -> None:
    """Un tentativo di consegna, con l'esito salvato (commit)."""
    now = now or datetime.now(UTC)
    if delivery.webhook_id is not None:
        if delivery.webhook is None or not delivery.webhook.enabled:
            delivery.status, delivery.last_error = "failed", "webhook disabled or deleted"
            session.commit()
            return
        ok, code, error = _send(client, delivery)
    else:
        from app import notifications

        ok, code, error = notifications.deliver(session, delivery)
    delivery.attempts += 1
    delivery.last_status_code, delivery.last_error = code, error
    if ok:
        delivery.status, delivery.delivered_at, delivery.next_attempt_at = "delivered", now, None
    elif delivery.attempts >= MAX_ATTEMPTS or delivery.event.name == "test":  # una prova non si ritenta
        delivery.status, delivery.next_attempt_at = "failed", None
        logger.warning("Consegna %s (%s) fallita dopo %d tentativi: %s",
                       delivery.id, delivery.event.name, delivery.attempts, error)
    else:
        delivery.next_attempt_at = now + BACKOFF[delivery.attempts - 1]
    session.commit()


def deliver_due(session: Session, client: httpx.Client | None = None, now: datetime | None = None) -> int:
    """Le consegne in attesa arrivate al loro momento; poi la pulizia di
    quelle vecchie. Restituisce quante ne ha tentate."""
    now = now or datetime.now(UTC)
    due = (
        session.query(EventDelivery)
        .filter(EventDelivery.status == "pending", EventDelivery.next_attempt_at <= now)
        .order_by(EventDelivery.id)
        .limit(BATCH)
        .all()
    )
    owns = client is None
    client = client or httpx.Client(follow_redirects=False)
    try:
        for delivery in due:
            try:
                attempt(session, delivery, client, now)
            except Exception:
                session.rollback()
                logger.exception("Consegna %s non tentata", delivery.id)
    finally:
        if owns:
            client.close()
    session.query(Event).filter(Event.created_at < now - RETENTION).delete(synchronize_session=False)
    session.commit()
    return len(due)
