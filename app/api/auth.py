"""Endpoint di login — deliberatamente MAI dietro app.auth.require_auth
(altrimenti nessuno potrebbe mai autenticarsi la prima volta). change-password
è protetto esplicitamente, sugli altri la sicurezza sta nel loro stesso
comportamento (setup rifiuta se già configurato, login verifica l'hash)."""

import hmac
import threading

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import auth, settings_repo
from app.api_errors import coded_detail
from app.deps import get_session

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


_setup_lock = threading.Lock()
# Per verificare comunque una password quando l'account non c'è.
_DUMMY_HASH = auth.hash_password("nazgarr-no-account")


@router.post("/setup", response_model=TokenResponse, status_code=201)
def setup(body: SetupRequest, request: Request, session: Session = Depends(get_session)):
    """Crea l'unico account amministratore — funziona SOLO se non ne
    esiste già uno, e solo con il codice monouso scritto nel log del
    container all'avvio (app.state.setup_code). Cambiare le credenziali dopo
    passa sempre da /change-password, protetto dalla password attuale."""
    with _setup_lock:  # due setup insieme: uno solo vince
        if auth.is_auth_configured(session):
            raise HTTPException(status_code=409, detail=coded_detail("auth_already_configured"))
        expected = getattr(request.app.state, "setup_code", None)
        if not expected or not hmac.compare_digest(body.setup_code.strip(), expected):
            raise HTTPException(status_code=403, detail=coded_detail("auth_setup_code_invalid"))
        if not body.username.strip():
            raise HTTPException(status_code=400, detail=coded_detail("auth_username_required"))
        if len(body.password) < 8:
            raise HTTPException(status_code=400, detail=coded_detail("auth_password_too_short"))
        settings_repo.set_setting(session, "auth_username", body.username.strip())
        settings_repo.set_setting(session, "auth_password_hash", auth.hash_password(body.password))
        request.app.state.setup_code = None
    token = auth.create_access_token(body.username.strip(), auth.token_version(session))
    return TokenResponse(access_token=token, username=body.username.strip())


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)):
    stored_username = settings_repo.get_setting(session, "auth_username")
    stored_hash = settings_repo.get_setting(session, "auth_password_hash")
    # La password si verifica sempre, anche con un nome sbagliato: lo stesso
    # tempo di risposta, niente indizi su quale dei due è giusto.
    password_ok = auth.verify_password(body.password, stored_hash or _DUMMY_HASH)
    username_ok = bool(stored_username) and hmac.compare_digest(body.username.encode(), stored_username.encode())
    if not (stored_hash and username_ok and password_ok):
        raise HTTPException(status_code=401, detail=coded_detail("auth_invalid_credentials"))
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
    body: ChangePasswordRequest, session: Session = Depends(get_session), _: str | None = Depends(auth.require_auth)
):
    stored_hash = settings_repo.get_setting(session, "auth_password_hash")
    if not stored_hash or not auth.verify_password(body.current_password, stored_hash):
        raise HTTPException(status_code=401, detail=coded_detail("auth_wrong_current_password"))
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail=coded_detail("auth_password_too_short"))
    settings_repo.set_setting(session, "auth_password_hash", auth.hash_password(body.new_password))
    # Ogni sessione aperta con la password vecchia smette di valere: chi
    # l'aveva rubata resta fuori. Il frontend rifà il login.
    auth.revoke_all_tokens(session)


@router.post("/logout-everywhere", status_code=204)
def logout_everywhere(session: Session = Depends(get_session), _: str | None = Depends(auth.require_auth)):
    """Esce da tutti i dispositivi: ogni token emesso finora smette di valere."""
    auth.revoke_all_tokens(session)
