"""Accesso a app_settings (key/value libero, docs/schema.sql — es.
tmdb_api_key, confidence_threshold_auto_*, schedule_cron).

Le impostazioni segrete (chiavi API, token, password, cookie) si salvano
cifrate come le credenziali di tracker e client (nazgarr/core/crypto.py), con un
prefisso che le distingue: un backup del DB non le rivela senza
APP_SECRET_KEY. Il login (auth_*) ha già solo l'hash della password."""

import re

from sqlalchemy.orm import Session

from nazgarr.core import crypto
from nazgarr.core.models import AppSetting

SECRET_KEY = re.compile(r"(api_key|token|password|secret|cookie)")
ENCRYPTED_PREFIX = "enc:"


# Chiavi che il loro proprietario gestisce già da sé: il canary di
# APP_SECRET_KEY (nazgarr/core/startup_checks.py) è già un token cifrato, cifrarlo di
# nuovo farebbe fallire il controllo all'avvio.
_OWN_FORMAT = frozenset({"app_secret_key_canary"})


def is_secret(key: str) -> bool:
    return bool(SECRET_KEY.search(key)) and not key.startswith("auth_") and key not in _OWN_FORMAT


def _decode(key: str, value: str) -> str:
    """Si decifra solo il valore di una chiave segreta: un "enc:..." salvato
    su una chiave qualunque (es. exclusion_patterns) faceva fallire ogni sua
    lettura, e con essa ogni vista della libreria (audit 2026-10-18)."""
    if is_secret(key) and value.startswith(ENCRYPTED_PREFIX):
        return crypto.decrypt(value[len(ENCRYPTED_PREFIX):])
    return value


def encode(key: str, value: str) -> str:
    """Come si salva un valore già nel DB (la migrazione dei segreti in
    chiaro, nazgarr/core/db.py): cifrato se la chiave è segreta e non lo è
    già."""
    if is_secret(key) and value and not value.startswith(ENCRYPTED_PREFIX):
        return ENCRYPTED_PREFIX + crypto.encrypt(value)
    return value


def get_setting(session: Session, key: str) -> str | None:
    row = session.get(AppSetting, key)
    return _decode(key, row.value) if row else None


def set_setting(session: Session, key: str, value: str) -> None:
    # Un valore nuovo è sempre in chiaro: cifrato anche se comincia per
    # "enc:", se no restava così e la lettura provava a decifrarlo.
    stored = ENCRYPTED_PREFIX + crypto.encrypt(value) if is_secret(key) and value else value
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=stored))
    else:
        row.value = stored
    session.commit()
