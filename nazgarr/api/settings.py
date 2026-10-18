"""API generica per app_settings (docs/SPEC.md — key/value libero, es.
tmdb_api_key). Non specifica per il resolver: le soglie, le opzioni e le
chiavi dei plugin passano da qui. Non le chiavi con un endpoint proprio o di
stato interno (settings_registry.MANAGED_KEYS: il cron dello scheduler, il
canary, le regole dei nomi, ...), che da qui non si scrivono."""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.core import settings_registry, settings_repo
from nazgarr.core.errors import coded_detail
from nazgarr.library.exclusions import DEFAULT_ENABLED_PRESETS, PRESETS
from nazgarr.web.deps import get_session

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingUpdateRequest(BaseModel):
    value: str


class SettingResponse(BaseModel):
    key: str
    value: str | None  # sempre None per una chiave segreta: si scrive, non si rilegge
    is_set: bool = False  # per una chiave segreta: se ne è salvato un valore


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


# Le credenziali del login hanno i loro endpoint (nazgarr/api/auth.py): da qui
# non si leggono né si scrivono, mai (l'hash della password, o sostituirlo).
_AUTH = re.compile(r"^auth_")
# Impostazioni segrete (chiavi API, token, password): la UI dopo il login le
# scrive, una API key no (nazgarr/web/api_keys.py). Nessuno le rilegge:
# come i segreti di tracker, client e plugin, l'API dice solo se ci sono
# (audit 2026-10-18; prima tornavano in chiaro a ogni sessione del browser).
_SECRET = settings_repo.SECRET_KEY


def _response(key: str, value: str | None) -> SettingResponse:
    if settings_repo.is_secret(key):
        return SettingResponse(key=key, value=None, is_set=bool(value))
    return SettingResponse(key=key, value=value, is_set=bool(value))


def _check_access(request: Request, key: str) -> None:
    if _AUTH.match(key):
        raise HTTPException(status_code=403, detail=coded_detail("setting_protected", key=key))
    # Si leggono, ma si scrivono solo dal loro endpoint (audit 2026-10-18).
    if request.method != "GET" and key in settings_registry.MANAGED_KEYS:
        raise HTTPException(status_code=403, detail=coded_detail("setting_protected", key=key))
    by_api_key = getattr(request.state, "api_key_id", None) is not None
    if by_api_key and _SECRET.search(key):
        raise HTTPException(status_code=403, detail=coded_detail("setting_secret_for_api_key", key=key))
    # Le protezioni (la verifica prima di eseguire, il recheck del client,
    # l'esecuzione automatica e le sue soglie): una API key le legge ma non
    # le cambia, spegnerle vorrebbe dire hardlink e torrent senza controlli.
    if by_api_key and request.method != "GET" and key in settings_registry.SAFETY_KEYS:
        raise HTTPException(status_code=403, detail=coded_detail("setting_safety_for_api_key", key=key))


@router.get("/{key}", response_model=SettingResponse)
def get_setting(key: str, request: Request, session: Session = Depends(get_session)):
    _check_access(request, key)
    return _response(key, settings_repo.get_setting(session, key))


@router.put("/{key}", response_model=SettingResponse)
def set_setting(key: str, body: SettingUpdateRequest, request: Request, session: Session = Depends(get_session)):
    _check_access(request, key)
    try:
        value = settings_registry.validate(key, body.value)
    except settings_registry.SettingValueError as exc:
        raise HTTPException(status_code=400, detail=coded_detail("setting_invalid_value", key=key)) from exc
    settings_repo.set_setting(session, key, value)
    return _response(key, value)
