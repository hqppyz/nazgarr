"""API di configurazione per le istanze Sonarr — vedi app/api/radarr_instances.py,
stesso ruolo e stesso stato (nessun adapter concreto le consuma ancora)."""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.types import HttpUrlStr, require_secrets_for_new_host
from app.api_errors import coded_detail
from app.deps import get_session
from app.models import SonarrInstance

router = APIRouter(prefix="/api/sonarr-instances", tags=["sonarr-instances"])

DEFAULT_PRIORITY = 0
DEFAULT_TIMEOUT_SECONDS = 15


class SonarrInstanceCreateRequest(BaseModel):
    label: str
    base_url: HttpUrlStr
    api_key: str
    priority: int = DEFAULT_PRIORITY
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


class SonarrInstanceUpdateRequest(BaseModel):
    label: str | None = None
    base_url: HttpUrlStr | None = None
    api_key: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    timeout_seconds: int | None = None
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


class SonarrInstanceResponse(BaseModel):
    id: int
    label: str
    base_url: str
    enabled: bool
    priority: int
    timeout_seconds: int
    basic_auth_username: str | None  # mai api_key/basic_auth_password: write-only, non tornano mai indietro

    @classmethod
    def from_model(cls, si: SonarrInstance) -> "SonarrInstanceResponse":
        return cls(
            id=si.id, label=si.label, base_url=si.base_url, enabled=si.enabled,
            priority=si.priority if si.priority is not None else DEFAULT_PRIORITY,
            timeout_seconds=si.timeout_seconds if si.timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS,
            basic_auth_username=si.basic_auth_username,
        )


class SonarrInstanceTestResponse(BaseModel):
    status: str  # "ok" | "error"
    version: str | None = None
    error: str | None = None


class SonarrConnectionTestRequest(BaseModel):
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
) -> SonarrInstanceTestResponse:
    """Sola lettura: vedi _test_connection in app/api/radarr_instances.py —
    stesso endpoint /api/v3/system/status, condiviso da tutta la famiglia
    Servarr."""
    auth = (basic_auth_username, basic_auth_password) if basic_auth_username else None
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/api/v3/system/status",
            headers={"X-Api-Key": api_key}, auth=auth, timeout=timeout_seconds,
        )
        response.raise_for_status()
        version = response.json().get("version")
    except Exception as exc:
        return SonarrInstanceTestResponse(status="error", error=str(exc))
    return SonarrInstanceTestResponse(status="ok", version=version)


def _get_or_404(session: Session, instance_id: int) -> SonarrInstance:
    instance = session.get(SonarrInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=coded_detail("sonarr_instance_not_found", id=instance_id))
    return instance


@router.get("", response_model=list[SonarrInstanceResponse])
def list_sonarr_instances(session: Session = Depends(get_session)):
    return [SonarrInstanceResponse.from_model(si) for si in session.query(SonarrInstance).all()]


@router.post("", response_model=SonarrInstanceResponse, status_code=201)
def create_sonarr_instance(body: SonarrInstanceCreateRequest, session: Session = Depends(get_session)):
    instance = SonarrInstance(
        label=body.label, base_url=body.base_url, api_key=body.api_key,
        priority=body.priority, timeout_seconds=body.timeout_seconds,
        basic_auth_username=body.basic_auth_username, basic_auth_password=body.basic_auth_password,
    )
    session.add(instance)
    session.commit()
    return SonarrInstanceResponse.from_model(instance)


@router.post("/test", response_model=SonarrInstanceTestResponse)
def test_sonarr_connection(body: SonarrConnectionTestRequest):
    return _test_connection(
        body.base_url, body.api_key, body.timeout_seconds, body.basic_auth_username, body.basic_auth_password
    )


@router.post("/{instance_id}/test", response_model=SonarrInstanceTestResponse)
def test_sonarr_instance(instance_id: int, session: Session = Depends(get_session)):
    """Come test_sonarr_connection ma contro le credenziali già salvate di
    un'istanza esistente — usata dal dialog "Edit instance" quando l'utente
    non ha ridigitato una nuova API key (write-only, non torna mai nel form)."""
    instance = _get_or_404(session, instance_id)
    timeout = instance.timeout_seconds if instance.timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS
    return _test_connection(
        instance.base_url, instance.api_key, timeout, instance.basic_auth_username, instance.basic_auth_password
    )


@router.patch("/{instance_id}", response_model=SonarrInstanceResponse)
def update_sonarr_instance(
    instance_id: int, body: SonarrInstanceUpdateRequest, session: Session = Depends(get_session)
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
    return SonarrInstanceResponse.from_model(instance)


@router.delete("/{instance_id}", status_code=204)
def delete_sonarr_instance(instance_id: int, session: Session = Depends(get_session)):
    instance = _get_or_404(session, instance_id)
    session.delete(instance)
    session.commit()
