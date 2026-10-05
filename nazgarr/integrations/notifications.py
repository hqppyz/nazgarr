"""Servizi di notifica (docs/ROADMAP.md Fase 10, step 6; istanze dalla
decisione dell'utente del 2026-10-05): ogni riga di notification_service è
un'istanza di un adapter "notification" (Discord, Telegram, quelli dei
plugin), con la sua configurazione e gli eventi a cui è iscritta. Riceve gli
eventi già trasformati in un messaggio leggibile, nel suo formato. Le
consegne passano dalla stessa coda dei webhook, con gli stessi ritentativi
(nazgarr/integrations/webhooks.py)."""

import json
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from nazgarr.adapters.notification.base import Notification
from nazgarr.core.models import NotificationService
from nazgarr.plugins import REGISTRY, AdapterContext
from nazgarr.plugins import config as plugin_config

logger = logging.getLogger(__name__)
ALL = "*"


def subscribed_events(service: NotificationService) -> list[str]:
    try:
        return json.loads(service.events_json or "[]") or [ALL]
    except ValueError:
        return [ALL]


def usable_config(service: NotificationService, *, even_if_disabled: bool = False) -> dict | None:
    """La configurazione che riceve l'adapter, se il servizio è acceso, il
    suo adapter c'è (un plugin può sparire) e ha i campi obbligatori."""
    spec = REGISTRY.get("notification", service.adapter_type)
    if spec is None or not (service.enabled or even_if_disabled):
        return None
    config = plugin_config.loads(service.config_json)
    if any(config.get(f.key) in (None, "") for f in spec.required_fields):
        return None
    return plugin_config.with_defaults(spec, config)


def targets(session: Session, name: str) -> list[NotificationService]:
    """I servizi accesi, configurati e iscritti all'evento."""
    out = []
    for service in session.query(NotificationService).order_by(NotificationService.id):
        if usable_config(service) is None:
            continue
        subscribed = subscribed_events(service)
        if ALL in subscribed or name in subscribed:
            out.append(service)
    return out


def _standard(name: str, data: dict) -> Notification:
    """Titolo e testo di ogni evento, in inglese come i log e gli eventi."""
    tracker = data.get("tracker")
    torrent = data.get("torrent")
    if name == "run.finished":
        state = "stopped" if data.get("stopped") else ("finished with errors" if data.get("errors") else "finished")
        return Notification(
            name, f"Scan {state}",
            f"{data.get('items_scanned', 0)} files scanned, {data.get('matches_found', 0)} matches, "
            f"{data.get('pending_review', 0)} to review. Health {data.get('health_pct', '?')}/100.",
            "warning" if data.get("errors") else "info", data,
        )
    if name == "review.created":
        automatic = data.get("status") == "auto_approved"
        return Notification(
            name, "Match approved automatically" if automatic else "Match to review",
            f"{torrent} on {tracker} (confidence {round((data.get('confidence') or 0) * 100)}%).",
            "info", data,
        )
    if name == "review.decided":
        return Notification(name, f"Review {data.get('status')}", f"{torrent} on {tracker}.", "info", data)
    if name == "seed_job.finished":
        ok = data.get("status") == "seeding"
        body = f"{torrent} on {tracker}." + ("" if ok else f" {data.get('error') or ''}".rstrip())
        return Notification(name, "Reseed seeding" if ok else "Reseed failed", body, "success" if ok else "error", data)
    if name == "upload.detected":
        return Notification(name, "New release detected", f"{data.get('path')} on {data.get('disk')}: upload started.",
                            "info", data)
    if name == "upload.ready":
        title = f"{data.get('title') or data.get('path')}" + (f" ({data['year']})" if data.get("year") else "")
        trackers = ", ".join(data.get("trackers") or [])
        return Notification(name, "Upload ready for your decision", f"{title}" + (f" → {trackers}" if trackers else ""),
                            "info", data)
    if name == "upload.finished":
        status = data.get("status")
        lines = [
            f"{t['tracker']}: {t['action']} {t['status']}" + (f" ({t['error']})" if t.get("error") else "")
            for t in data.get("targets", []) if t.get("action") and t.get("action") != "skip"
        ]
        level = {"done": "success", "partial": "warning", "failed": "error"}.get(status, "info")
        title = f"Upload {status}: {data.get('title') or ''}".rstrip(": ")
        return Notification(name, title, "\n".join(lines) or "Nothing to do.", level, data)
    if name == "test":
        return Notification(name, "Nazgarr test", "Notifications from Nazgarr work.", "info", data)
    return Notification(name, name, json.dumps(data, default=str), "info", data)


# Come un evento diventa testo, per servizio (notification_service.message_format).
# Per ora uno solo; un formato nuovo (più compatto, per esempio) è una
# funzione in più qui, e l'API lo accetta da sola.
FORMATS: dict[str, Callable[[str, dict], Notification]] = {"standard": _standard}
DEFAULT_FORMAT = "standard"


def render(name: str, data: dict, message_format: str = DEFAULT_FORMAT) -> Notification:
    return FORMATS.get(message_format, _standard)(name, data)


def send(adapter_type: str, config: dict, notification: Notification, session: Session | None = None) -> None:
    """Manda una notifica con quell'adapter e quella configurazione (già con i default)."""
    spec = REGISTRY.get("notification", adapter_type)
    if spec is None:
        raise LookupError(f"notification adapter {adapter_type!r} not available")
    spec.build(AdapterContext(config=config, session=session)).send(notification)


def deliver(session: Session, delivery) -> tuple[bool, int | None, str | None]:
    """Una consegna a un servizio di notifica: (riuscita, codice, errore)."""
    service = delivery.notification
    # La prova si manda anche a un servizio spento: serve a provarlo prima di accenderlo.
    test = delivery.event.name == "test"
    config = usable_config(service, even_if_disabled=test) if service is not None else None
    if config is None:
        return False, None, "notification service not available (deleted, disabled, not configured or plugin removed)"
    try:
        send(service.adapter_type, config,
             render(delivery.event.name, json.loads(delivery.event.payload_json), service.message_format), session)
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"[:500]
    return True, None, None
