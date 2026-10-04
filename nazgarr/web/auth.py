"""Login JWT (Fase 9) — protegge le API e la WebUI dietro un unico account
amministratore, mai basic auth. Le credenziali vivono in app_settings
(auth_username/auth_password_hash), coerente con "tutto tranne i mount
point vive nel DB, editabile da UI" (CLAUDE.md). Il login è obbligatorio
(decisione dell'utente, 2026-10-01): finché l'account non esiste, tutto è
chiuso tranne /api/auth/*, e per crearlo serve il codice monouso stampato
nel log (o NAZGARR_SETUP_CODE).

Il segreto di firma JWT riusa APP_SECRET_KEY (già l'unico segreto che
questo progetto richiede via env, usato per cifrare le credenziali in
nazgarr/core/crypto.py) invece di introdurne un secondo da gestire."""

import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from nazgarr.core import settings_repo
from nazgarr.core.crypto import SecretKeyMissingError
from nazgarr.core.errors import coded_detail
from nazgarr.web import api_keys
from nazgarr.web.deps import get_session

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


# Versione dei token: è nel token ("ver") e nel DB. Cambiare la password o
# "esci da tutti i dispositivi" la alza, e ogni token emesso prima smette di
# valere subito, invece di restare buono fino alla scadenza (30 giorni).
_TOKEN_VERSION_KEY = "auth_token_version"


def token_version(session: Session) -> str:
    return settings_repo.get_setting(session, _TOKEN_VERSION_KEY) or "1"


def revoke_all_tokens(session: Session) -> None:
    current = int(token_version(session)) if token_version(session).isdigit() else 1
    settings_repo.set_setting(session, _TOKEN_VERSION_KEY, str(current + 1))


def create_access_token(username: str, version: str = "1") -> str:
    payload = {"sub": username, "ver": version, "exp": int(time.time()) + _TOKEN_TTL_SECONDS}
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def decode_access_claims(token: str) -> dict | None:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def decode_access_token(token: str) -> str | None:
    claims = decode_access_claims(token)
    return claims.get("sub") if claims else None


def authenticated_username(request: Request, session: Session) -> str | None:
    """None se l'header manca, il token è invalido/scaduto, o non
    corrisponde all'unico account configurato — mai un'eccezione qui,
    il chiamante decide cosa fare (require_auth la solleva, /api/auth/me no)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    claims = decode_access_claims(auth_header.removeprefix("Bearer ")) or {}
    username = claims.get("sub")
    stored_username = settings_repo.get_setting(session, "auth_username")
    if username is None or stored_username is None or username != stored_username:
        return None
    # I token di prima di questa versione non hanno "ver": valgono come "1".
    if str(claims.get("ver", "1")) != token_version(session):
        return None
    return username


SETUP_CODE_ENV = "NAZGARR_SETUP_CODE"


def new_setup_code() -> str:
    """Il codice monouso per creare l'account al primo avvio (decisione
    dell'utente, 2026-10-01): da NAZGARR_SETUP_CODE se c'è, se no casuale.
    Vive solo in memoria e si scrive nel log del container: chi raggiunge la
    porta ma non vede il log non può creare l'account al posto tuo."""
    return os.environ.get(SETUP_CODE_ENV) or secrets.token_urlsafe(9)


def _api_key(request: Request, session: Session):
    """La API key dell'header X-Api-Key, se c'è (nazgarr/web/api_keys.py): una
    chiave sbagliata o revocata è sempre un 401; una di sola lettura su un
    metodo che scrive un 403."""
    raw = request.headers.get(api_keys.HEADER)
    if raw is None:
        return None
    key = api_keys.authenticate(session, raw)
    if key is None:
        raise HTTPException(status_code=401, detail=coded_detail("api_key_invalid"))
    if not api_keys.allows(key, request.method):
        raise HTTPException(status_code=403, detail=coded_detail("api_key_read_only"))
    request.state.api_key_id = key.id
    return key


def require_auth(request: Request, session: Session = Depends(get_session)) -> str | None:
    """Dependency applicata a ogni router protetto (nazgarr/main.py). Il login è
    obbligatorio: finché l'account non esiste, tutto è chiuso tranne
    /api/auth/* (per crearlo, con il codice monouso del log) — prima era
    aperto, e chiunque in rete aveva il pieno controllo. Accetta anche una
    API key (X-Api-Key), con i suoi limiti."""
    key = _api_key(request, session)
    if key is not None:
        return f"api-key:{key.name}"
    if not is_auth_configured(session):
        raise HTTPException(status_code=401, detail=coded_detail("auth_setup_required"))
    username = authenticated_username(request, session)
    if username is None:
        raise HTTPException(status_code=401, detail=coded_detail("auth_required"))
    return username


def require_login(request: Request, session: Session = Depends(get_session)) -> str | None:
    """Come require_auth, ma una API key non basta: per le cose che una
    chiave non deve poter fare (creare o revocare API key)."""
    if request.headers.get(api_keys.HEADER) is not None:
        raise HTTPException(status_code=403, detail=coded_detail("api_key_not_allowed"))
    return require_auth(request, session)
