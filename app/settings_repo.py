"""Accesso a app_settings (key/value libero, docs/schema.sql — es.
tmdb_api_key, confidence_threshold_auto_*, schedule_cron).

Le impostazioni segrete (chiavi API, token, password, cookie) si salvano
cifrate come le credenziali di tracker e client (app/crypto.py), con un
prefisso che le distingue: un backup del DB non le rivela senza
APP_SECRET_KEY. Il login (auth_*) ha già solo l'hash della password."""

import re

from sqlalchemy.orm import Session

from app import crypto
from app.models import AppSetting

SECRET_KEY = re.compile(r"(api_key|token|password|secret|cookie)")
ENCRYPTED_PREFIX = "enc:"


# Chiavi che il loro proprietario gestisce già da sé: il canary di
# APP_SECRET_KEY (app/startup_checks.py) è già un token cifrato, cifrarlo di
# nuovo farebbe fallire il controllo all'avvio.
_OWN_FORMAT = frozenset({"app_secret_key_canary"})


def is_secret(key: str) -> bool:
    return bool(SECRET_KEY.search(key)) and not key.startswith("auth_") and key not in _OWN_FORMAT


def _decode(value: str) -> str:
    return crypto.decrypt(value[len(ENCRYPTED_PREFIX):]) if value.startswith(ENCRYPTED_PREFIX) else value


def encode(key: str, value: str) -> str:
    """Come si salva un valore: cifrato se la chiave è segreta."""
    if is_secret(key) and value and not value.startswith(ENCRYPTED_PREFIX):
        return ENCRYPTED_PREFIX + crypto.encrypt(value)
    return value


def get_setting(session: Session, key: str) -> str | None:
    row = session.get(AppSetting, key)
    return _decode(row.value) if row else None


def set_setting(session: Session, key: str, value: str) -> None:
    stored = encode(key, value)
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=stored))
    else:
        row.value = stored
    session.commit()
