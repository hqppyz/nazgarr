"""API generica per app_settings (docs/SPEC.md — key/value libero, es.
tmdb_api_key). Non specifica per il resolver: qualunque chiave futura
(soglie di confidence, cron dello scheduler) passa da qui."""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import settings_repo
from app.api_errors import coded_detail
from app.deps import get_session
from app.exclusions import DEFAULT_ENABLED_PRESETS, PRESETS

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingUpdateRequest(BaseModel):
    value: str


class SettingResponse(BaseModel):
    key: str
    value: str | None


class ExclusionPresetResponse(BaseModel):
    key: str
    patterns: list[str]
    enabled_by_default: bool  # attivo finché exclusion_presets non viene mai salvato


@router.get("/exclusion-presets/available", response_model=list[ExclusionPresetResponse])
def list_exclusion_presets():
    """Preset pronti per esclusioni note (sidecar dei client torrent più
    comuni + spazzatura tipica di release scena) — l'utente li abilita in
    Impostazioni senza doverne conoscere i pattern esatti."""
    return [
        ExclusionPresetResponse(key=key, patterns=patterns, enabled_by_default=key in DEFAULT_ENABLED_PRESETS)
        for key, patterns in PRESETS.items()
    ]


# Le credenziali del login hanno i loro endpoint (app/api/auth.py): da qui
# non si leggono né si scrivono, mai (l'hash della password, o sostituirlo).
_AUTH = re.compile(r"^auth_")
# Impostazioni segrete (chiavi API, token, password): la UI dopo il login le
# usa, una API key no (app/api_keys.py).
_SECRET = re.compile(r"(api_key|token|password|secret)")


def _check_access(request: Request, key: str) -> None:
    if _AUTH.match(key):
        raise HTTPException(status_code=403, detail=coded_detail("setting_protected", key=key))
    if getattr(request.state, "api_key_id", None) is not None and _SECRET.search(key):
        raise HTTPException(status_code=403, detail=coded_detail("setting_secret_for_api_key", key=key))


@router.get("/{key}", response_model=SettingResponse)
def get_setting(key: str, request: Request, session: Session = Depends(get_session)):
    _check_access(request, key)
    return SettingResponse(key=key, value=settings_repo.get_setting(session, key))


@router.put("/{key}", response_model=SettingResponse)
def set_setting(key: str, body: SettingUpdateRequest, request: Request, session: Session = Depends(get_session)):
    _check_access(request, key)
    settings_repo.set_setting(session, key, body.value)
    return SettingResponse(key=key, value=body.value)
