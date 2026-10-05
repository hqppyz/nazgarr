"""Gestione delle API key (nazgarr/web/api_keys.py): solo con il login, mai con
un'altra API key (nazgarr/web/auth.py require_login)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.core.errors import coded_detail
from nazgarr.core.models import ApiKey
from nazgarr.web import api_keys
from nazgarr.web.deps import get_session

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    prefix: str
    level: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def from_model(cls, key: ApiKey) -> "ApiKeyResponse":
        return cls(id=key.id, name=key.name, prefix=key.prefix, level=key.level, created_at=key.created_at,
                   last_used_at=key.last_used_at, revoked_at=key.revoked_at)


class ApiKeyCreateRequest(BaseModel):
    name: str
    level: str  # read | write


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str  # l'unica volta che si vede


@router.get("", response_model=list[ApiKeyResponse])
def list_api_keys(session: Session = Depends(get_session)):
    return [ApiKeyResponse.from_model(k) for k in session.query(ApiKey).order_by(ApiKey.id.desc())]


@router.post("", response_model=ApiKeyCreatedResponse, status_code=201)
def create_api_key(body: ApiKeyCreateRequest, session: Session = Depends(get_session)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail=coded_detail("api_key_name_required"))
    if body.level not in api_keys.LEVELS:
        raise HTTPException(status_code=400, detail=coded_detail("api_key_level_invalid", level=body.level))
    key, raw = api_keys.create(session, body.name, body.level)
    return ApiKeyCreatedResponse(**ApiKeyResponse.from_model(key).model_dump(), key=raw)


@router.post("/{key_id}/revoke", response_model=ApiKeyResponse)
def revoke_api_key(key_id: int, session: Session = Depends(get_session)):
    key = session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail=coded_detail("api_key_not_found", id=key_id))
    api_keys.revoke(session, key)
    return ApiKeyResponse.from_model(key)
