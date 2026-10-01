"""API key per servizi e script (docs/ROADMAP.md Fase 10, decisione
dell'utente 2026-09-30: due livelli, lettura e scrittura).

Una chiave è "nzg_" più 32 byte casuali: si mostra una volta sola alla
creazione e si salva solo il suo SHA-256 (è già casuale e lunga: nessun
bisogno di un hash lento come per le password). Si passa nell'header
X-Api-Key.

- read: solo GET (e HEAD/OPTIONS);
- write: tutto quello che può fare chi ha fatto login, tranne gestire le
  API key, che richiede il login vero (require_login): una chiave rubata
  non può crearne altre per restare dentro.

Le azioni su file e client passano comunque dalla coda di approvazione,
come per chiunque.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import ApiKey

HEADER = "X-Api-Key"
PREFIX = "nzg_"
LEVELS = ("read", "write")
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# last_used_at si aggiorna al massimo una volta in questo intervallo: niente
# scrittura sul DB a ogni richiesta di uno script che fa polling.
TOUCH_EVERY = timedelta(minutes=1)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create(session: Session, name: str, level: str) -> tuple[ApiKey, str]:
    """(la riga, la chiave in chiaro: l'unica volta che esiste)."""
    if level not in LEVELS:
        raise ValueError(level)
    raw = PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(name=name.strip(), prefix=raw[:12], key_hash=hash_key(raw), level=level)
    session.add(key)
    session.commit()
    return key, raw


def authenticate(session: Session, raw: str) -> ApiKey | None:
    if not raw or not raw.startswith(PREFIX):
        return None
    key = session.query(ApiKey).filter_by(key_hash=hash_key(raw)).one_or_none()
    if key is None or key.revoked_at is not None:
        return None
    now = datetime.now(UTC)
    last = key.last_used_at
    if last is not None and last.tzinfo is None:  # SQLite restituisce datetime naive
        last = last.replace(tzinfo=UTC)
    if last is None or now - last >= TOUCH_EVERY:
        key.last_used_at = now
        session.commit()
    return key


def allows(key: ApiKey, method: str) -> bool:
    return key.level == "write" or method.upper() in READ_METHODS


def revoke(session: Session, key: ApiKey) -> None:
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        session.commit()
