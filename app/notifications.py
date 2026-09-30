"""Servizi di notifica (docs/ROADMAP.md Fase 10, step 6): adapter dei
plugin iscritti agli eventi di app/events.py. Finché lo step 6 non c'è,
nessun iscritto."""

from sqlalchemy.orm import Session


def targets(session: Session, name: str) -> list[str]:
    return []


def deliver(session: Session, delivery) -> tuple[bool, int | None, str | None]:
    """Consegna a un servizio di notifica (step 6)."""
    return False, None, "notifications are not available yet"
