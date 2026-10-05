"""API di configurazione delle istanze Radarr e Sonarr: multi-istanza (stesso
pattern di tracker e client torrent), usate da nazgarr/integrations/arr.py per l'indice
dei file e la history, sempre opzionali (docs/SPEC.md §2/§6).

Radarr e Sonarr hanno la stessa API REST v3 e la stessa configurazione:
un router solo, costruito per ognuno da make_router
(nazgarr/api/radarr_instances.py, nazgarr/api/sonarr_instances.py, che
tengono i nomi dei modelli dello schema OpenAPI usati dal frontend)."""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.api.types import HttpUrlStr, require_secrets_for_new_host
from nazgarr.core.errors import coded_detail
from nazgarr.core.logs import safe_error
from nazgarr.web.deps import get_session

DEFAULT_PRIORITY = 0
DEFAULT_TIMEOUT_SECONDS = 15


class ArrInstanceCreateRequest(BaseModel):
    label: str
    base_url: HttpUrlStr
    api_key: str
    priority: int = DEFAULT_PRIORITY
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


class ArrInstanceUpdateRequest(BaseModel):
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


class ArrInstanceResponse(BaseModel):
    id: int
    label: str
    base_url: str
    enabled: bool
    priority: int
    timeout_seconds: int
    basic_auth_username: str | None  # mai api_key/basic_auth_password: write-only, non tornano mai indietro

    @classmethod
    def from_model(cls, row):
        return cls(
            id=row.id, label=row.label, base_url=row.base_url, enabled=row.enabled,
            priority=row.priority if row.priority is not None else DEFAULT_PRIORITY,
            timeout_seconds=row.timeout_seconds if row.timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS,
            basic_auth_username=row.basic_auth_username,
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
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
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
            reply = httpx.get(
                f"{base_url.rstrip('/')}/api/v3/system/status",
                headers={"X-Api-Key": api_key}, auth=auth, timeout=timeout_seconds,
            )
            reply.raise_for_status()
            version = reply.json().get("version")
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
        return [response.from_model(row) for row in session.query(model).all()]

    @router.post("", response_model=response, status_code=201, name=f"create_{kind}_instance")
    def create_instance(body: create_request, session: Session = Depends(get_session)):  # type: ignore[valid-type]
        instance = model(
            label=body.label, base_url=body.base_url, api_key=body.api_key,
            priority=body.priority, timeout_seconds=body.timeout_seconds,
            basic_auth_username=body.basic_auth_username, basic_auth_password=body.basic_auth_password,
        )
        session.add(instance)
        session.commit()
        return response.from_model(instance)

    @router.post("/test", response_model=test_response, name=f"test_{kind}_connection")
    def test_new_connection(body: connection_request):  # type: ignore[valid-type]
        return test_connection(
            body.base_url, body.api_key, body.timeout_seconds, body.basic_auth_username, body.basic_auth_password
        )

    @router.post("/{instance_id}/test", response_model=test_response, name=f"test_{kind}_instance")
    def test_saved_instance(instance_id: int, session: Session = Depends(get_session)):
        """Come il test di una connessione nuova, con le credenziali salvate:
        dal dialog "Edit instance" quando l'API key (write-only) non è stata
        ridigitata."""
        instance = get_or_404(session, instance_id)
        timeout = instance.timeout_seconds if instance.timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS
        return test_connection(
            instance.base_url, instance.api_key, timeout, instance.basic_auth_username, instance.basic_auth_password
        )

    @router.patch("/{instance_id}", response_model=response, name=f"update_{kind}_instance")
    def update_instance(instance_id: int, body: update_request, session: Session = Depends(get_session)):  # type: ignore[valid-type]
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
        return response.from_model(instance)

    @router.delete("/{instance_id}", status_code=204, name=f"delete_{kind}_instance")
    def delete_instance(instance_id: int, session: Session = Depends(get_session)):
        instance = get_or_404(session, instance_id)
        session.delete(instance)
        session.commit()

    return router
