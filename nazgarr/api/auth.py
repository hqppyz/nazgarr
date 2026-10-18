"""Endpoint di login — deliberatamente MAI dietro app.auth.require_auth
(altrimenti nessuno potrebbe mai autenticarsi la prima volta). change-password
e logout-everywhere sono protetti esplicitamente, e solo dal login: una API key
non tocca mai il login stesso (docs/SDK.md, audit 2026-10-18). Sugli altri la
sicurezza sta nel loro stesso comportamento (setup rifiuta se già
configurato, login verifica l'hash)."""

import hmac
import threading

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.core import settings_repo
from nazgarr.core.errors import coded_detail
from nazgarr.web import auth, login_limiter
from nazgarr.web.deps import get_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthStatusResponse(BaseModel):
    configured: bool


class SetupRequest(BaseModel):
    username: str
    password: str
    setup_code: str  # quello scritto nel log del container al primo avvio


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    username: str


class MeResponse(BaseModel):
    username: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/status", response_model=AuthStatusResponse)
def auth_status(session: Session = Depends(get_session)):
    return AuthStatusResponse(configured=auth.is_auth_configured(session))


def _client_key(request: Request, scope: str = "") -> str:
    """L'indirizzo del client (quello vero dietro un reverse proxy solo con
    FORWARDED_ALLOW_IPS, README), con il prefisso di un conto separato."""
    host = request.client.host if request.client else "unknown"
    return f"{scope}:{host}" if scope else host


def _reserve(request: Request, scope: str = "") -> tuple[str, float]:
    """Prenota il tentativo prima di verificare (nazgarr/web/login_limiter.py),
    o 429 se il limite è raggiunto. Conta come errore finché non arriva
    succeeded() o release()."""
    key = _client_key(request, scope)
    try:
        return key, login_limiter.reserve(key)
    except login_limiter.TooManyAttempts as exc:
        raise HTTPException(status_code=429, detail=coded_detail("auth_too_many_attempts", seconds=exc.wait),
                            headers={"Retry-After": str(exc.wait)}) from exc


def _not_a_failure(attempt: tuple[str, float], status_code: int, code: str) -> HTTPException:
    login_limiter.release(*attempt)
    return HTTPException(status_code=status_code, detail=coded_detail(code))


_setup_lock = threading.Lock()
# Per verificare comunque una password quando l'account non c'è.
_DUMMY_HASH = auth.hash_password("nazgarr-no-account")


@router.post("/setup", response_model=TokenResponse, status_code=201)
def setup(body: SetupRequest, request: Request, session: Session = Depends(get_session)):
    """Crea l'unico account amministratore — funziona SOLO se non ne
    esiste già uno, e solo con il codice monouso scritto nel log del
    container all'avvio (app.state.setup_code). Cambiare le credenziali dopo
    passa sempre da /change-password, protetto dalla password attuale."""
    attempt = _reserve(request)
    with _setup_lock:  # due setup insieme: uno solo vince
        if auth.is_auth_configured(session):
            raise _not_a_failure(attempt, 409, "auth_already_configured")
        expected = getattr(request.app.state, "setup_code", None)
        # In byte: compare_digest su due str con caratteri non ASCII solleva
        # TypeError (un 500 a chiunque mandasse una "é").
        if not expected or not hmac.compare_digest(body.setup_code.strip().encode(), expected.encode()):
            raise HTTPException(status_code=403, detail=coded_detail("auth_setup_code_invalid"))
        if not body.username.strip():
            raise _not_a_failure(attempt, 400, "auth_username_required")
        if len(body.password) < 8:
            raise _not_a_failure(attempt, 400, "auth_password_too_short")
        settings_repo.set_setting(session, "auth_username", body.username.strip())
        settings_repo.set_setting(session, "auth_password_hash", auth.hash_password(body.password))
        request.app.state.setup_code = None
    login_limiter.succeeded(attempt[0])
    token = auth.create_access_token(body.username.strip(), auth.token_version(session))
    return TokenResponse(access_token=token, username=body.username.strip())


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, session: Session = Depends(get_session)):
    attempt = _reserve(request)
    stored_username = settings_repo.get_setting(session, "auth_username")
    stored_hash = settings_repo.get_setting(session, "auth_password_hash")
    # La password si verifica sempre, anche con un nome sbagliato: lo stesso
    # tempo di risposta, niente indizi su quale dei due è giusto.
    password_ok = auth.verify_password(body.password, stored_hash or _DUMMY_HASH)
    username_ok = bool(stored_username) and hmac.compare_digest(body.username.encode(), stored_username.encode())
    if not (stored_hash and username_ok and password_ok):
        raise HTTPException(status_code=401, detail=coded_detail("auth_invalid_credentials"))
    login_limiter.succeeded(attempt[0])
    token = auth.create_access_token(stored_username, auth.token_version(session))
    return TokenResponse(access_token=token, username=stored_username)


@router.get("/me", response_model=MeResponse)
def me(request: Request, session: Session = Depends(get_session)):
    username = auth.authenticated_username(request, session)
    if username is None:
        raise HTTPException(status_code=401, detail=coded_detail("auth_required"))
    return MeResponse(username=username)


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordRequest, request: Request, session: Session = Depends(get_session),
    _: str | None = Depends(auth.require_login),
):
    # Un conto suo: gli errori qui non bloccano il login dallo stesso indirizzo.
    attempt = _reserve(request, "pw")
    stored_hash = settings_repo.get_setting(session, "auth_password_hash")
    if not stored_hash or not auth.verify_password(body.current_password, stored_hash):
        raise HTTPException(status_code=401, detail=coded_detail("auth_wrong_current_password"))
    if len(body.new_password) < 8:
        raise _not_a_failure(attempt, 400, "auth_password_too_short")
    login_limiter.succeeded(attempt[0])
    settings_repo.set_setting(session, "auth_password_hash", auth.hash_password(body.new_password))
    # Ogni sessione aperta con la password vecchia smette di valere: chi
    # l'aveva rubata resta fuori. Il frontend rifà il login.
    auth.revoke_all_tokens(session)


@router.post("/logout-everywhere", status_code=204)
def logout_everywhere(session: Session = Depends(get_session), _: str | None = Depends(auth.require_login)):
    """Esce da tutti i dispositivi: ogni token emesso finora smette di valere.
    Solo col login: una API key di scrittura rubata, in un ciclo, avrebbe
    buttato fuori l'amministratore a ogni nuovo accesso."""
    auth.revoke_all_tokens(session)
