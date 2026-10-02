"""Servizi di notifica dei plugin (docs/ROADMAP.md Fase 10, step 6): ogni
adapter "notification" acceso e configurato (nazgarr/plugins/config.py) riceve
gli eventi a cui è iscritto (adapter_config.events_json, null = tutti),
già trasformati in un messaggio leggibile. Le consegne passano dalla
stessa coda dei webhook, con gli stessi ritentativi (nazgarr/webhooks.py)."""

import json
import logging

from sqlalchemy.orm import Session

from nazgarr.adapters.notification.base import Notification
from nazgarr.plugins import REGISTRY, AdapterContext
from nazgarr.plugins import config as plugin_config

logger = logging.getLogger(__name__)
ALL = "*"


def subscribed_events(session: Session, adapter_type: str) -> list[str]:
    row = plugin_config.global_config(session, "notification", adapter_type)
    if row is None or not row.events_json:
        return [ALL]
    try:
        return json.loads(row.events_json) or [ALL]
    except ValueError:
        return [ALL]


def targets(session: Session, name: str) -> list[str]:
    """I servizi accesi, configurati e iscritti all'evento."""
    out = []
    for spec in REGISTRY.of_kind("notification"):
        if plugin_config.usable_global(session, spec) is None:
            continue
        subscribed = subscribed_events(session, spec.adapter_type)
        if ALL in subscribed or name in subscribed:
            out.append(spec.adapter_type)
    return out


def render(name: str, data: dict) -> Notification:
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


def deliver(session: Session, delivery) -> tuple[bool, int | None, str | None]:
    """Una consegna a un servizio di notifica: (riuscita, codice, errore)."""
    spec = REGISTRY.get("notification", delivery.notification_type)
    config = plugin_config.usable_global(session, spec) if spec is not None else None
    if spec is None or config is None:
        return False, None, "notification service not available (plugin removed, disabled or not configured)"
    try:
        adapter = spec.build(AdapterContext(config=config, session=session))
        adapter.send(render(delivery.event.name, json.loads(delivery.event.payload_json)))
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"[:500]
    return True, None, None
