"""Login JWT (Fase 9) — protegge le API e la WebUI dietro un unico account
amministratore, mai basic auth. Le credenziali vivono in app_settings
(auth_username/auth_password_hash), coerente con "tutto tranne i mount
point vive nel DB, editabile da UI" (CLAUDE.md). Il login è obbligatorio
(decisione dell'utente, 2026-10-01): finché l'account non esiste, tutto è
chiuso tranne /api/auth/*, e per crearlo serve il codice monouso stampato
nel log (o NAZGARR_SETUP_CODE).

Il segreto di firma JWT riusa APP_SECRET_KEY (già l'unico segreto che
questo progetto richiede via env, usato per cifrare le credenziali in
nazgarr/core/crypto.py) invece di introdurne un secondo da gestire.

Audit 2026-10-18: la password si deriva con 600.000 iterazioni (OWASP), e un
hash più debole si rifà al login riuscito successivo; i token portano "aud",
un identificativo casuale di questa installazione, così due istanze con la
stessa chiave e lo stesso utente non accettano i token l'una dell'altra. I
token di prima (senza "aud") valgono fino alla loro scadenza naturale: un
aggiornamento non butta fuori nessuno."""

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

_PBKDF2_ITERATIONS = 600_000  # OWASP per PBKDF2-HMAC-SHA256; prima 260.000
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


def needs_rehash(stored_hash: str | None) -> bool:
    """Un hash valido ma con meno iterazioni di quelle di adesso: il login
    riuscito lo rifà (nazgarr/api/auth.py), la password è lì in chiaro."""
    try:
        algo, iterations, _salt, _digest = (stored_hash or "").split("$")
        return algo == "pbkdf2_sha256" and int(iterations) < _PBKDF2_ITERATIONS
    except ValueError:
        return False


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


# Il claim "aud" dei token: casuale, uno per installazione, creato all'avvio
# (nazgarr/main.py). Con lui la data fino a cui valgono ancora i token di
# prima, che non l'hanno: la loro scadenza più lontana possibile.
_AUDIENCE_KEY = "auth_token_audience"
_LEGACY_UNTIL_KEY = "auth_legacy_tokens_until"


def token_audience(session: Session) -> str:
    audience = settings_repo.get_setting(session, _AUDIENCE_KEY)
    if audience:
        return audience
    # Senza account non c'è nessun token di prima da lasciar valere.
    legacy_until = int(time.time()) + _TOKEN_TTL_SECONDS if is_auth_configured(session) else 0
    settings_repo.set_setting(session, _LEGACY_UNTIL_KEY, str(legacy_until))
    audience = f"nazgarr:{secrets.token_urlsafe(16)}"
    settings_repo.set_setting(session, _AUDIENCE_KEY, audience)
    return audience


def _legacy_tokens_until(session: Session) -> int:
    value = settings_repo.get_setting(session, _LEGACY_UNTIL_KEY) or ""
    return int(value) if value.isdigit() else 0


def create_access_token(username: str, version: str = "1", audience: str | None = None) -> str:
    now = int(time.time())
    payload = {"sub": username, "ver": version, "iat": now, "exp": now + _TOKEN_TTL_SECONDS}
    if audience is not None:
        payload["aud"] = audience
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def issue_token(session: Session, username: str) -> str:
    return create_access_token(username, token_version(session), token_audience(session))


def decode_access_claims(token: str, audience: str | None = None, legacy_until: int = 0) -> dict | None:
    """I claim di un token valido, se no None. Con un audience, un token di
    un'altra installazione non vale; uno senza "aud" (di prima) solo se scade
    entro legacy_until."""
    try:
        claims = jwt.decode(token, _jwt_secret(), algorithms=["HS256"],
                            options={"require": ["exp", "sub"], "verify_aud": False})
    except jwt.PyJWTError:
        return None
    if "aud" in claims:
        return claims if claims["aud"] == audience else None
    if audience is not None and claims["exp"] > legacy_until:
        return None
    return claims


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
    claims = decode_access_claims(auth_header.removeprefix("Bearer "), token_audience(session),
                                  _legacy_tokens_until(session)) or {}
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
