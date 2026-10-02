"""API di configurazione per le istanze Radarr — multi-istanza da subito
(stesso pattern di tracker/torrent_client), anche se nessun adapter le
consuma ancora (docs/SPEC.md SS2/SS6: content-identification opzionale,
mai richiesta dal resolver)."""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.api.types import HttpUrlStr, require_secrets_for_new_host
from nazgarr.api_errors import coded_detail
from nazgarr.deps import get_session
from nazgarr.logging_config import safe_error
from nazgarr.models import RadarrInstance

router = APIRouter(prefix="/api/radarr-instances", tags=["radarr-instances"])

DEFAULT_PRIORITY = 0
DEFAULT_TIMEOUT_SECONDS = 15


class RadarrInstanceCreateRequest(BaseModel):
    label: str
    base_url: HttpUrlStr
    api_key: str
    priority: int = DEFAULT_PRIORITY
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


class RadarrInstanceUpdateRequest(BaseModel):
    label: str | None = None
    base_url: HttpUrlStr | None = None
    api_key: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    timeout_seconds: int | None = None
    # Stringa vuota = disattiva la basic auth (cancella sia username che
    # password); None = campo non toccato da questa richiesta.
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


class RadarrInstanceResponse(BaseModel):
    id: int
    label: str
    base_url: str
    enabled: bool
    priority: int
    timeout_seconds: int
    basic_auth_username: str | None  # mai api_key/basic_auth_password: write-only, non tornano mai indietro

    @classmethod
    def from_model(cls, ri: RadarrInstance) -> "RadarrInstanceResponse":
        return cls(
            id=ri.id, label=ri.label, base_url=ri.base_url, enabled=ri.enabled,
            priority=ri.priority if ri.priority is not None else DEFAULT_PRIORITY,
            timeout_seconds=ri.timeout_seconds if ri.timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS,
            basic_auth_username=ri.basic_auth_username,
        )


class RadarrInstanceTestResponse(BaseModel):
    status: str  # "ok" | "error"
    version: str | None = None
    error: str | None = None


class RadarrConnectionTestRequest(BaseModel):
    """Senza instance_id: usata dal dialog "Add instance" per testare prima
    ancora di salvare, con i valori appena digitati nel form."""

    base_url: HttpUrlStr
    api_key: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


def _test_connection(
    base_url: str, api_key: str, timeout_seconds: int,
    basic_auth_username: str | None, basic_auth_password: str | None,
) -> RadarrInstanceTestResponse:
    """Sola lettura: chiama GET /api/v3/system/status, comune a tutta la
    famiglia Servarr (Radarr/Sonarr condividono la stessa shape REST v3) —
    non serve un adapter completo solo per verificare le credenziali."""
    auth = (basic_auth_username, basic_auth_password) if basic_auth_username else None
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/api/v3/system/status",
            headers={"X-Api-Key": api_key}, auth=auth, timeout=timeout_seconds,
        )
        response.raise_for_status()
        version = response.json().get("version")
    except Exception as exc:
        return RadarrInstanceTestResponse(status="error", error=safe_error(exc))
    return RadarrInstanceTestResponse(status="ok", version=version)


def _get_or_404(session: Session, instance_id: int) -> RadarrInstance:
    instance = session.get(RadarrInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=coded_detail("radarr_instance_not_found", id=instance_id))
    return instance


@router.get("", response_model=list[RadarrInstanceResponse])
def list_radarr_instances(session: Session = Depends(get_session)):
    return [RadarrInstanceResponse.from_model(ri) for ri in session.query(RadarrInstance).all()]


@router.post("", response_model=RadarrInstanceResponse, status_code=201)
def create_radarr_instance(body: RadarrInstanceCreateRequest, session: Session = Depends(get_session)):
    instance = RadarrInstance(
        label=body.label, base_url=body.base_url, api_key=body.api_key,
        priority=body.priority, timeout_seconds=body.timeout_seconds,
        basic_auth_username=body.basic_auth_username, basic_auth_password=body.basic_auth_password,
    )
    session.add(instance)
    session.commit()
    return RadarrInstanceResponse.from_model(instance)


@router.post("/test", response_model=RadarrInstanceTestResponse)
def test_radarr_connection(body: RadarrConnectionTestRequest):
    return _test_connection(
        body.base_url, body.api_key, body.timeout_seconds, body.basic_auth_username, body.basic_auth_password
    )


@router.post("/{instance_id}/test", response_model=RadarrInstanceTestResponse)
def test_radarr_instance(instance_id: int, session: Session = Depends(get_session)):
    """Come test_radarr_connection ma contro le credenziali già salvate di
    un'istanza esistente — usata dal dialog "Edit instance" quando l'utente
    non ha ridigitato una nuova API key (write-only, non torna mai nel form)."""
    instance = _get_or_404(session, instance_id)
    timeout = instance.timeout_seconds if instance.timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS
    return _test_connection(
        instance.base_url, instance.api_key, timeout, instance.basic_auth_username, instance.basic_auth_password
    )


@router.patch("/{instance_id}", response_model=RadarrInstanceResponse)
def update_radarr_instance(
    instance_id: int, body: RadarrInstanceUpdateRequest, session: Session = Depends(get_session)
):
    instance = _get_or_404(session, instance_id)
    missing = [name for name, stored, sent in (
        ("api_key", instance.api_key, body.api_key),
        ("basic_auth_password", instance.basic_auth_password, body.basic_auth_password),
    ) if stored and sent is None]
    require_secrets_for_new_host(instance.base_url, body.base_url, missing)
    if body.label is not None:
        instance.label = body.label
    if body.base_url is not None:
        instance.base_url = body.base_url
    if body.api_key is not None:
        instance.api_key = body.api_key
    if body.enabled is not None:
        instance.enabled = body.enabled
    if body.priority is not None:
        instance.priority = body.priority
    if body.timeout_seconds is not None:
        instance.timeout_seconds = body.timeout_seconds
    if body.basic_auth_username is not None:
        instance.basic_auth_username = body.basic_auth_username or None
    if body.basic_auth_password is not None:
        instance.basic_auth_password = body.basic_auth_password or None
    session.commit()
    return RadarrInstanceResponse.from_model(instance)


@router.delete("/{instance_id}", status_code=204)
def delete_radarr_instance(instance_id: int, session: Session = Depends(get_session)):
    instance = _get_or_404(session, instance_id)
    session.delete(instance)
    session.commit()
