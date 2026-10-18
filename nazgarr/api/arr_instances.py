"""API di configurazione delle istanze Radarr e Sonarr: multi-istanza (stesso
pattern di tracker e client torrent), usate da nazgarr/integrations/arr.py per l'indice
dei file e la history, sempre opzionali (docs/SPEC.md §2/§6).

Radarr e Sonarr hanno la stessa API REST v3 e la stessa configurazione:
un router solo, costruito per ognuno da make_router
(nazgarr/api/radarr_instances.py, nazgarr/api/sonarr_instances.py, che
tengono i nomi dei modelli dello schema OpenAPI usati dal frontend)."""

import json
import time
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, object_session

from nazgarr.api.types import HttpUrlStr, check_destinations, insecure_public_url, require_secrets_for_new_host
from nazgarr.core import http_limits
from nazgarr.core.errors import coded_detail
from nazgarr.core.logs import safe_error
from nazgarr.integrations import arr as arr_api
from nazgarr.integrations import arr_webhooks
from nazgarr.web.deps import get_session

DEFAULT_PRIORITY = 0
DEFAULT_TIMEOUT_SECONDS = 15
# Secondi di attesa di una risposta: da 1 a 5 minuti. Un valore negativo
# arrivava a httpx come timeout non valido, e ogni chiamata a quell'istanza
# falliva con un errore che non diceva perché (audit 2026-10-18).
TIMEOUT_MAX_SECONDS = 300
# /system/status è qualche KB: una risposta più grande non è Radarr/Sonarr.
MAX_STATUS_BYTES = 1024 * 1024


def status_client(auth, timeout_seconds: int) -> httpx.Client:
    """Il client HTTP della prova di connessione (sostituibile nei test)."""
    return httpx.Client(auth=auth, timeout=timeout_seconds)


class ArrInstanceCreateRequest(BaseModel):
    label: str
    base_url: HttpUrlStr
    api_key: str
    priority: int = DEFAULT_PRIORITY
    timeout_seconds: int = Field(DEFAULT_TIMEOUT_SECONDS, ge=1, le=TIMEOUT_MAX_SECONDS)
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


class ArrInstanceUpdateRequest(BaseModel):
    label: str | None = None
    base_url: HttpUrlStr | None = None
    api_key: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=TIMEOUT_MAX_SECONDS)
    # Stringa vuota = disattiva la basic auth (cancella sia username che
    # password); None = campo non toccato da questa richiesta.
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


class ArrWebhookEventSummary(BaseModel):
    """L'ultimo evento ricevuto dal webhook: per dire che il collegamento funziona."""
    event_type: str
    status: str  # pending | done | ignored | failed
    detail: str | None
    received_at: datetime


class ArrWebhookSetupResponse(BaseModel):
    """La password del webhook, mostrata solo quando la si crea: il percorso
    va sull'indirizzo con cui Radarr/Sonarr raggiungono Nazgarr."""
    path: str
    token: str


class ArrInstanceResponse(BaseModel):
    id: int
    label: str
    base_url: str
    # http:// verso un host pubblico: l'API key viaggia in chiaro. Salvato lo
    # stesso, con un avviso (decisione dell'utente, 2026-10-18).
    insecure_public_url: bool = False
    enabled: bool
    priority: int
    timeout_seconds: int
    basic_auth_username: str | None  # mai api_key/basic_auth_password: write-only, non tornano mai indietro
    webhook_enabled: bool = False  # la password del webhook non torna mai, solo se c'è
    webhook_last_event: ArrWebhookEventSummary | None = None

    @classmethod
    def from_model(cls, row, kind: str | None = None):
        session = object_session(row)
        last = arr_webhooks.last_event(session, kind, row.id) if session is not None and kind else None
        return cls(
            id=row.id, label=row.label, base_url=row.base_url, insecure_public_url=insecure_public_url(row.base_url),
            enabled=row.enabled,
            priority=row.priority if row.priority is not None else DEFAULT_PRIORITY,
            timeout_seconds=row.timeout_seconds if row.timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS,
            basic_auth_username=row.basic_auth_username,
            webhook_enabled=bool(row.webhook_token),
            webhook_last_event=ArrWebhookEventSummary(
                event_type=last.event_type, status=last.status, detail=last.detail, received_at=last.received_at,
            ) if last is not None else None,
        )


class ArrInstanceTestResponse(BaseModel):
    status: str  # "ok" | "error"
    version: str | None = None
    error: str | None = None


class ArrConnectionTestRequest(BaseModel):
    """Senza instance_id: usata dal dialog "Add instance" per testare prima
    ancora di salvare, con i valori appena digitati nel form."""

    base_url: HttpUrlStr
    api_key: str
    timeout_seconds: int = Field(DEFAULT_TIMEOUT_SECONDS, ge=1, le=TIMEOUT_MAX_SECONDS)
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


def make_router(
    kind: str, model, *, create_request: type[ArrInstanceCreateRequest], update_request: type[ArrInstanceUpdateRequest],
    response: type[ArrInstanceResponse], test_response: type[ArrInstanceTestResponse],
    connection_request: type[ArrConnectionTestRequest],
) -> APIRouter:
    """Il router di /api/{kind}-instances (kind: "radarr" | "sonarr")."""
    router = APIRouter(prefix=f"/api/{kind}-instances", tags=[f"{kind}-instances"])

    def test_connection(base_url: str, api_key: str, timeout_seconds: int, basic_auth_username: str | None,
                        basic_auth_password: str | None):
        """Sola lettura: GET /api/v3/system/status, comune a tutta la famiglia
        Servarr: non serve un adapter completo per verificare le credenziali."""
        auth = (basic_auth_username, basic_auth_password) if basic_auth_username else None
        try:
            # Letta in streaming con un tetto (nazgarr/core/http_limits.py), come l'indice.
            with status_client(auth, timeout_seconds) as client, client.stream(
                "GET", f"{base_url.rstrip('/')}/api/v3/system/status",
                headers={"X-Api-Key": api_key, "Accept-Encoding": http_limits.ACCEPT_ENCODING},
            ) as reply:
                reply.raise_for_status()
                body = http_limits.read_limited(reply, MAX_STATUS_BYTES, time.monotonic() + 4 * timeout_seconds)
            status = json.loads(body)
            version = status.get("version") if isinstance(status, dict) else None
        except Exception as exc:
            return test_response(status="error", error=safe_error(exc))
        return test_response(status="ok", version=version)

    def get_or_404(session: Session, instance_id: int):
        instance = session.get(model, instance_id)
        if instance is None:
            raise HTTPException(status_code=404, detail=coded_detail(f"{kind}_instance_not_found", id=instance_id))
        return instance

    @router.get("", response_model=list[response], name=f"list_{kind}_instances")
    def list_instances(session: Session = Depends(get_session)):
        return [response.from_model(row, kind) for row in session.query(model).all()]

    @router.post("", response_model=response, status_code=201, name=f"create_{kind}_instance")
    def create_instance(body: create_request, session: Session = Depends(get_session)):  # type: ignore[valid-type]
        check_destinations(body.base_url)
        instance = model(
            label=body.label, base_url=body.base_url, api_key=body.api_key,
            priority=body.priority, timeout_seconds=body.timeout_seconds,
            basic_auth_username=body.basic_auth_username, basic_auth_password=body.basic_auth_password,
        )
        session.add(instance)
        session.commit()
        return response.from_model(instance, kind)

    @router.post("/test", response_model=test_response, name=f"test_{kind}_connection")
    def test_new_connection(body: connection_request):  # type: ignore[valid-type]
        check_destinations(body.base_url)
        return test_connection(
            body.base_url, body.api_key, body.timeout_seconds, body.basic_auth_username, body.basic_auth_password
        )

    @router.post("/{instance_id}/test", response_model=test_response, name=f"test_{kind}_instance")
    def test_saved_instance(instance_id: int, session: Session = Depends(get_session)):
        """Come il test di una connessione nuova, con le credenziali salvate:
        dal dialog "Edit instance" quando l'API key (write-only) non è stata
        ridigitata."""
        instance = get_or_404(session, instance_id)
        check_destinations(instance.base_url)  # a ogni richiesta, non solo quando l'indirizzo si salva
        timeout = arr_api.timeout_of(instance)
        return test_connection(
            instance.base_url, instance.api_key, timeout, instance.basic_auth_username, instance.basic_auth_password
        )

    @router.patch("/{instance_id}", response_model=response, name=f"update_{kind}_instance")
    def update_instance(instance_id: int, body: update_request, session: Session = Depends(get_session)):  # type: ignore[valid-type]
        check_destinations(body.base_url)
        instance = get_or_404(session, instance_id)
        missing = [name for name, stored, sent in (
            ("api_key", instance.api_key, body.api_key),
            ("basic_auth_password", instance.basic_auth_password, body.basic_auth_password),
        ) if stored and sent is None]
        require_secrets_for_new_host(instance.base_url, body.base_url, missing)
        for field in ("label", "base_url", "api_key", "enabled", "priority", "timeout_seconds"):
            value = getattr(body, field)
            if value is not None:
                setattr(instance, field, value)
        if body.basic_auth_username is not None:
            instance.basic_auth_username = body.basic_auth_username or None
        if body.basic_auth_password is not None:
            instance.basic_auth_password = body.basic_auth_password or None
        session.commit()
        return response.from_model(instance, kind)

    @router.post("/{instance_id}/webhook", response_model=ArrWebhookSetupResponse, name=f"setup_{kind}_webhook")
    def setup_webhook(instance_id: int, session: Session = Depends(get_session)):
        """Crea (o rigenera) la password del webhook: quella vecchia smette
        subito di valere. Si vede solo qui (nazgarr/integrations/arr_webhooks.py)."""
        instance = get_or_404(session, instance_id)
        instance.webhook_token = arr_webhooks.new_token()
        session.commit()
        return ArrWebhookSetupResponse(path=f"/api/arr-hooks/{kind}/{instance.id}", token=instance.webhook_token)

    @router.delete("/{instance_id}/webhook", status_code=204, name=f"remove_{kind}_webhook")
    def remove_webhook(instance_id: int, session: Session = Depends(get_session)):
        instance = get_or_404(session, instance_id)
        instance.webhook_token = None
        session.commit()

    @router.delete("/{instance_id}", status_code=204, name=f"delete_{kind}_instance")
    def delete_instance(instance_id: int, session: Session = Depends(get_session)):
        instance = get_or_404(session, instance_id)
        session.delete(instance)
        session.commit()

    return router
