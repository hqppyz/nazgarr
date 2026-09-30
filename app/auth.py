"""Login JWT (Fase 9) — protegge le API e la WebUI dietro un unico account
amministratore, mai basic auth. Le credenziali vivono in app_settings
(auth_username/auth_password_hash), coerente con "tutto tranne i mount
point vive nel DB, editabile da UI" (CLAUDE.md) — finché non sono
configurate, l'app resta aperta esattamente come oggi: nessuna rottura per
chi aggiorna un'istanza già in uso senza aver mai impostato un login.

Il segreto di firma JWT riusa APP_SECRET_KEY (già l'unico segreto che
questo progetto richiede via env, usato per cifrare le credenziali in
app/crypto.py) invece di introdurne un secondo da gestire."""

import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import settings_repo
from app.api_errors import coded_detail
from app.crypto import SecretKeyMissingError
from app.deps import get_session

_PBKDF2_ITERATIONS = 260_000
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 giorni — self-hosted, nessun refresh flow per ora


def _jwt_secret() -> str:
    key = os.environ.get("APP_SECRET_KEY")
    if not key:
        raise SecretKeyMissingError(
            "APP_SECRET_KEY non impostata: necessaria anche per firmare i token di login."
        )
    return key


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations, salt, digest = stored_hash.split("$")
        if algo != "pbkdf2_sha256":
            return False
        computed = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(computed, digest)
    except (ValueError, AttributeError):
        return False


def is_auth_configured(session: Session) -> bool:
    return bool(settings_repo.get_setting(session, "auth_username")) and bool(
        settings_repo.get_setting(session, "auth_password_hash")
    )


def create_access_token(username: str) -> str:
    payload = {"sub": username, "exp": int(time.time()) + _TOKEN_TTL_SECONDS}
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return payload.get("sub")


def authenticated_username(request: Request, session: Session) -> str | None:
    """None se l'header manca, il token è invalido/scaduto, o non
    corrisponde all'unico account configurato — mai un'eccezione qui,
    il chiamante decide cosa fare (require_auth la solleva, /api/auth/me no)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    username = decode_access_token(auth_header.removeprefix("Bearer "))
    stored_username = settings_repo.get_setting(session, "auth_username")
    if username is None or stored_username is None or username != stored_username:
        return None
    return username


SETUP_CODE_ENV = "NAZGARR_SETUP_CODE"


def new_setup_code() -> str:
    """Il codice monouso per creare l'account al primo avvio (decisione
    dell'utente, 2026-10-01): da NAZGARR_SETUP_CODE se c'è, se no casuale.
    Vive solo in memoria e si scrive nel log del container: chi raggiunge la
    porta ma non vede il log non può creare l'account al posto tuo."""
    return os.environ.get(SETUP_CODE_ENV) or secrets.token_urlsafe(9)


def require_auth(request: Request, session: Session = Depends(get_session)) -> str | None:
    """Dependency applicata a ogni router protetto (app/main.py). Il login è
    obbligatorio: finché l'account non esiste, tutto è chiuso tranne
    /api/auth/* (per crearlo, con il codice monouso del log) — prima era
    aperto, e chiunque in rete aveva il pieno controllo."""
    if not is_auth_configured(session):
        raise HTTPException(status_code=401, detail=coded_detail("auth_setup_required"))
    username = authenticated_username(request, session)
    if username is None:
        raise HTTPException(status_code=401, detail=coded_detail("auth_required"))
    return username
