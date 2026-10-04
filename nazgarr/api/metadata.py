"""Metadati TMDB per la schermata di match dell'upload (docs/SPEC.md §9
"Upload flow v2"): ricerca manuale, dettagli di un candidato e poster.

I poster dei candidati di solito non sono nella cache della libreria (il
contenuto non è ancora stato scansionato): questo endpoint li scarica una
volta nella stessa cache (nazgarr/library/poster_cache.py) e li serve da lì, così la
chiave TMDB resta sul server e il browser non parla mai con TMDB.
"""

import logging
import os
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from nazgarr.core.errors import coded_detail, from_coded_error
from nazgarr.core.logs import safe_error
from nazgarr.integrations.adapter_factory import TmdbApiKeyMissingError
from nazgarr.library.poster_cache import download_poster, poster_file
from nazgarr.upload import identify as upload_identify
from nazgarr.web.deps import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/metadata", tags=["metadata"])

# Solo un nome file di image.tmdb.org, mai un URL: l'host resta fisso.
_POSTER_PATH = re.compile(r"^/[A-Za-z0-9_-]+\.(jpg|jpeg|png)$")


def _content_type(value: str) -> str:
    if value not in ("movie", "tv"):
        raise HTTPException(status_code=400, detail=coded_detail("invalid_content_type", value=value))
    return value


def _client(session: Session):
    try:
        return upload_identify.tmdb_client(session)
    except TmdbApiKeyMissingError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc


def _tmdb_call(fn, *args):
    try:
        return fn(*args)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail=coded_detail("tmdb_not_found")) from exc
        raise HTTPException(status_code=502, detail=coded_detail("tmdb_error", error=safe_error(exc))) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=coded_detail("tmdb_error", error=safe_error(exc))) from exc


@router.get("/search")
def search(
    content_type: str,
    query: str = Query(min_length=1),
    year: int | None = None,
    language: str | None = Query(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$"),
    session: Session = Depends(get_session),
) -> list[dict]:
    """language (es. "it-IT"): i titoli nella lingua dell'interfaccia."""
    client = _client(session)
    return _tmdb_call(client.search_many, _content_type(content_type), query, year, language)[:20]


@router.get("/{content_type}/{tmdb_id}")
def details(
    content_type: str,
    tmdb_id: int,
    language: str | None = Query(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$"),
    session: Session = Depends(get_session),
) -> dict:
    """language (es. "it-IT"): trama, titolo e generi nella lingua
    dell'interfaccia; quello che lì manca, in inglese."""
    client = _client(session)
    return _tmdb_call(client.full_details, _content_type(content_type), tmdb_id, language)


@router.get("/posters/{content_type}/{tmdb_id}.jpg")
def poster(
    content_type: str, tmdb_id: int, request: Request, path: str | None = None, session: Session = Depends(get_session)
):
    content_type = _content_type(content_type)
    posters_dir = os.path.join(request.app.state.settings.data_dir, "posters")
    local_path = poster_file(posters_dir, content_type, tmdb_id)
    if not os.path.isfile(local_path):
        poster_path = path if path and _POSTER_PATH.match(path) else None
        if poster_path is None:
            poster_path = _tmdb_call(_client(session).full_details, content_type, tmdb_id).get("poster_path")
        if not poster_path:
            raise HTTPException(status_code=404, detail=coded_detail("poster_not_available"))
        try:
            download_poster(posters_dir, content_type, tmdb_id, poster_path)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=coded_detail("tmdb_error", error=safe_error(exc))) from exc
    return FileResponse(local_path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
