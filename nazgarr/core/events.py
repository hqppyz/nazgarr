"""Eventi di Nazgarr per webhook e notifiche (docs/ROADMAP.md Fase 10).

Un evento si salva nella tabella event, con una consegna (event_delivery)
per ogni webhook iscritto, nella stessa transazione del cambiamento che lo
causa: se il cambiamento non va a buon fine non parte niente, e un riavvio
non perde consegne. Il dispatcher (nazgarr/integrations/webhooks.py) le invia con i
ritentativi. Senza nessun iscritto non si salva niente.

La maggior parte degli eventi nasce da sola da un cambio di stato nel DB
(hook di SQLAlchemy, qui sotto): una review creata o decisa, un seed job
che finisce, una run che termina, ovunque avvenga nel codice. Quelli che
passano da un UPDATE in blocco (le transizioni degli upload) si emettono con
emit().

Il payload di ogni evento è la parte "data" della consegna; la forma è parte
del contratto dell'SDK (docs/SDK.md): si aggiungono campi, non si tolgono.
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

CATALOG: dict[str, str] = {
    "run.finished": "A scan and matching run finished (also when stopped or with errors).",
    "review.created": "A match is waiting for your review, or was approved automatically.",
    "review.decided": "A review was approved or rejected.",
    "seed_job.finished": "A reseed is seeding, or it failed.",
    "upload.detected": "A new release in a watched folder started an upload.",
    "upload.ready": "An upload is analysed and waits for your decision.",
    "upload.finished": "An upload job finished: done, partial, failed or cancelled.",
    "test": "Sent by \"Send a test\", to try a webhook or a notification service.",
}
ALL = "*"
_PENDING = "nazgarr_pending_events"
SEED_JOB_FINAL = ("seeding", "failed")
REVIEW_DECIDED = ("approved", "rejected", "auto_approved")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def webhook_targets(session: Session, name: str) -> list:
    from nazgarr.core.models import Webhook

    out = []
    for webhook in session.query(Webhook).filter(Webhook.enabled.is_(True)).all():
        try:
            names = json.loads(webhook.events_json or "[]")
        except ValueError:
            names = []
        if ALL in names or name in names:
            out.append(webhook)
    return out


def notification_targets(session: Session, name: str) -> list:
    """I servizi di notifica iscritti all'evento (step 6)."""
    from nazgarr.integrations import notifications

    return notifications.targets(session, name)


def store(
    session: Session, name: str, data: dict, *, only_webhook_id: int | None = None,
    only_notification_id: int | None = None,
) -> object | None:
    """Salva l'evento e le sue consegne (senza commit). None se nessuno è
    iscritto. only_*: una consegna sola a quel destinatario (l'invio di prova)."""
    from nazgarr.core.models import Event, EventDelivery, NotificationService, Webhook

    only = only_webhook_id is not None or only_notification_id is not None
    with session.no_autoflush:
        webhooks = webhook_targets(session, name) if not only else []
        notifications = notification_targets(session, name) if not only else []
        if only_webhook_id is not None:
            webhook = session.get(Webhook, only_webhook_id)
            webhooks = [webhook] if webhook is not None else []
        if only_notification_id is not None:
            service = session.get(NotificationService, only_notification_id)
            notifications = [service] if service is not None else []
    if not webhooks and not notifications:
        return None
    now = datetime.now(UTC)
    event = Event(name=name, payload_json=json.dumps(data, default=str), created_at=now)
    event.deliveries = [
        EventDelivery(webhook_id=w.id, status="pending", next_attempt_at=now, created_at=now) for w in webhooks
    ] + [
        EventDelivery(notification_id=n.id, status="pending", next_attempt_at=now, created_at=now)
        for n in notifications
    ]
    session.add(event)
    return event


def emit(session: Session, name: str, data: dict) -> None:
    """Un evento emesso a mano (senza commit: lo fa il chiamante)."""
    if name not in CATALOG:
        raise ValueError(f"evento sconosciuto: {name!r}")
    try:
        store(session, name, data)
    except Exception:  # un evento non deve mai rompere l'operazione che lo causa
        logger.exception("Evento %s non salvato", name)


# --- dai cambi di stato nel DB --------------------------------------------------


def _changed_to(obj, attr: str, values: tuple[str, ...]) -> bool:
    from sqlalchemy import inspect

    history = inspect(obj).attrs[attr].history
    return bool(history.added) and history.added[0] in values and history.added[0] not in (history.deleted or ())


def _before_flush(session: Session, _flush_context, _instances) -> None:
    from sqlalchemy import inspect

    from nazgarr.core.models import MatchReview, RunLog, SeedJob

    pending = session.info.setdefault(_PENDING, [])
    for obj in session.new:
        if isinstance(obj, MatchReview):
            pending.append(("review.created", obj))
        elif isinstance(obj, SeedJob) and obj.final_status in SEED_JOB_FINAL:
            pending.append(("seed_job.finished", obj))
    for obj in session.dirty:
        if isinstance(obj, MatchReview) and _changed_to(obj, "status", REVIEW_DECIDED):
            pending.append(("review.decided", obj))
        elif isinstance(obj, SeedJob) and _changed_to(obj, "final_status", SEED_JOB_FINAL):
            pending.append(("seed_job.finished", obj))
        elif isinstance(obj, RunLog):
            history = inspect(obj).attrs["finished_at"].history
            if history.added and history.added[0] is not None and not any(history.deleted or ()):
                pending.append(("run.finished", obj))


def _payload(session: Session, name: str, obj) -> dict:
    from nazgarr.core.models import Candidate, Tracker

    if name == "run.finished":
        return {
            "run_id": obj.id, "run_type": obj.run_type, "started_at": _iso(obj.started_at),
            "finished_at": _iso(obj.finished_at), "errors": obj.errors, "items_scanned": obj.items_scanned,
            "matches_found": obj.matches_found, "auto_executed": obj.auto_executed,
            "pending_review": obj.pending_review, "health_pct": obj.health_snapshot,
            "stopped": bool(obj.last_error and obj.last_error.startswith("Stopped")),
        }
    candidate = session.get(Candidate, obj.candidate_id)
    tracker = session.get(Tracker, candidate.tracker_id) if candidate is not None else None
    torrent = {
        "candidate_id": obj.candidate_id, "torrent": candidate.name if candidate else None,
        "tracker": tracker.label if tracker else None,
        "torrent_id_remote": candidate.torrent_id_remote if candidate else None,
    }
    if name == "review.created":
        return {"review_id": obj.id, "status": obj.status, "media_file_id": obj.media_file_id,
                "seed_file_id": obj.seed_file_id, "confidence": candidate.confidence if candidate else None,
                "direction": candidate.direction if candidate else None, **torrent}
    if name == "review.decided":
        return {"review_id": obj.id, "status": obj.status, "decided_by": obj.decided_by, **torrent}
    if name == "seed_job.finished":
        return {"seed_job_id": obj.id, "status": obj.final_status, "info_hash": obj.info_hash,
                "error": obj.error_message, "recheck_skipped": bool(obj.recheck_skipped), **torrent}
    return {}


def _after_flush_postexec(session: Session, _flush_context) -> None:
    pending = session.info.pop(_PENDING, None)
    if not pending:
        return
    seen = set()
    for name, obj in pending:
        key = (name, type(obj).__name__, obj.id)
        if key in seen:
            continue
        seen.add(key)
        try:
            with session.no_autoflush:
                store(session, name, _payload(session, name, obj))
        except Exception:  # mai rompere il commit di chi ha causato l'evento
            logger.exception("Evento %s non salvato", name)


def _after_rollback(session: Session) -> None:
    session.info.pop(_PENDING, None)


sa_event.listen(Session, "before_flush", _before_flush)
sa_event.listen(Session, "after_flush_postexec", _after_flush_postexec)
sa_event.listen(Session, "after_soft_rollback", lambda session, _tx: _after_rollback(session))
