"""Lettura dello stato unificato per file (docs/SPEC.md sezione 3) e la
vista Libreria (sezione 7) — media_item raggruppati coi loro media_file,
base dati condivisa per la futura vista ad albero e a griglia poster
(il frontend che le renderizza non è ancora costruito, il progetto resta
API-only fino a quel punto)."""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import (
    adapter_factory,
    duplicates,
    library,
    library_detail,
    matching,
    response_cache,
    settings_repo,
    tracker_scope,
)
from app.api.reviews import ReviewResponse
from app.api_errors import coded_detail
from app.deps import get_session
from app.exclusions import CompiledExclusions, load_exclusions
from app.models import MediaFile, MediaItem, RunLog, Tracker
from app.poster_cache import poster_file

router = APIRouter(prefix="/api", tags=["library"])


def _load_exclusions(session: Session) -> CompiledExclusions:
    return load_exclusions(session)


class MediaFileState(BaseModel):
    id: int
    disk_id: int
    relative_path: str
    size_bytes: int
    state: str
    stopped: bool = False  # seeding, ma ogni torrent che lo contiene è fermo nel client
    excluded: bool
    linked_paths: list[str]
    # Contenuto a cui appartiene il file (per aprire la scheda di dettaglio),
    # None se il file non ha un'identità (non risolto, nfo, immagini...).
    content_type: str | None = None
    tmdb_id: int | None = None


class SeedFileState(BaseModel):
    id: int
    disk_id: int
    relative_path: str
    size_bytes: int
    media_file_id: int | None
    state: str
    stopped: bool = False
    excluded: bool
    linked_paths: list[str]
    # Orfano, ma lo stesso file (hardlink) è in seed da questi altri percorsi.
    seeding_copies: list[str] = []
    content_type: str | None = None  # dal file in libreria collegato, se c'è
    tmdb_id: int | None = None


class MediaItemFile(BaseModel):
    media_file_id: int
    disk_id: int
    relative_path: str
    size_bytes: int = 0
    state: str
    stopped: bool = False
    excluded: bool
    linked_paths: list[str]
    duplicate: bool = False  # altra copia dello stesso contenuto su un inode diverso
    in_review: bool = False  # match trovato, in attesa di approvazione in Reseeding


class DuplicateFile(BaseModel):
    media_file_id: int
    disk_id: int
    relative_path: str


class DuplicateGroup(BaseModel):
    content_hash: str | None
    size_bytes: int
    kind: str = "copy"  # copy (inode diversi, spazio sprecato) | hardlink (stesso inode, più percorsi)
    files: list[DuplicateFile]


class MediaItemOverview(BaseModel):
    id: int
    content_type: str
    tmdb_id: int
    season_number: int | None
    episode_number: int | None
    has_poster: bool
    title: str | None = None
    year: int | None = None
    files: list[MediaItemFile]


# Le tre risposte pesanti delle viste (decine di migliaia di righe) passano
# da app/response_cache.py: ETag sulla versione dei dati, 304 se il browser
# ha già quella versione, ricalcolo una sola volta quando cambia. Il
# response_model resta per lo schema OpenAPI (tipi del frontend).
@router.get("/media-files", response_model=list[MediaFileState])
def list_media_files(
    request: Request, disk_id: int | None = None, tracker: str | None = None, session: Session = Depends(get_session)
):
    tracker = tracker_scope.normalize(tracker)  # filtro per tracker (app/tracker_scope.py)
    return response_cache.cached_json(
        request, session, f"media-files:{disk_id}:{tracker}",
        lambda: library.media_file_states(
            session, disk_id=disk_id, exclusions=_load_exclusions(session), tracker=tracker
        ),
    )


@router.get("/seed-files", response_model=list[SeedFileState])
def list_seed_files(
    request: Request, disk_id: int | None = None, tracker: str | None = None, session: Session = Depends(get_session)
):
    tracker = tracker_scope.normalize(tracker)  # filtro per tracker (app/tracker_scope.py)
    return response_cache.cached_json(
        request, session, f"seed-files:{disk_id}:{tracker}",
        lambda: library.seed_file_states(
            session, disk_id=disk_id, exclusions=_load_exclusions(session), tracker=tracker
        ),
    )


@router.get("/library/items", response_model=list[MediaItemOverview])
def list_library_items(
    request: Request, disk_id: int | None = None, tracker: str | None = None, session: Session = Depends(get_session)
):
    tracker = tracker_scope.normalize(tracker)  # filtro per tracker (app/tracker_scope.py)
    return response_cache.cached_json(
        request, session, f"items:{disk_id}:{tracker}",
        lambda: library.media_items_overview(
            session, disk_id=disk_id, exclusions=_load_exclusions(session), tracker=tracker
        ),
    )


@router.get("/library/unmatched", response_model=list[MediaFileState])
def list_unmatched(disk_id: int | None = None, session: Session = Depends(get_session)):
    return library.unmatched_media_files(session, disk_id=disk_id, exclusions=_load_exclusions(session))


@router.get("/library/duplicates", response_model=list[DuplicateGroup])
def list_duplicates(request: Request, disk_id: int | None = None, session: Session = Depends(get_session)):
    """Copie non intenzionali dello stesso contenuto su inode diversi —
    file già hardlinkati fra loro non compaiono qui (app/duplicates.py)."""
    return response_cache.cached_json(
        request, session, f"duplicates:{disk_id}",
        lambda: duplicates.find_duplicate_media_files(session, disk_id=disk_id),
    )


@router.get("/library/posters/{content_type}/{tmdb_id}.jpg")
def get_poster(content_type: str, tmdb_id: int, request: Request):
    posters_dir = os.path.join(request.app.state.settings.data_dir, "posters")
    local_path = poster_file(posters_dir, content_type, tmdb_id)
    if not os.path.isfile(local_path):
        raise HTTPException(status_code=404, detail=coded_detail("poster_not_cached"))
    # Il frontend li scarica con fetch + header di autenticazione (un <img>
    # non manda l'header): la cache del browser evita di riscaricarli.
    return FileResponse(local_path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


class DetailTorrent(BaseModel):
    name: str
    client: str
    tracker: str | None
    state: str
    client_enabled: bool = True


class DetailHardlink(BaseModel):
    relative_path: str
    torrents: list[DetailTorrent]


class DetailDuplicate(BaseModel):
    relative_path: str
    size_bytes: int
    same_file: bool = False  # stesso inode (hardlink): eliminarlo non libera spazio e non tocca il seed


class DetailFile(BaseModel):
    media_file_id: int
    disk_id: int  # per aprire un upload su questo file (pagina di nuovo upload)
    season_number: int | None
    episode_number: int | None
    relative_path: str
    size_bytes: int
    is_video: bool
    state: str
    stopped: bool = False
    excluded: bool
    in_review: bool
    hardlinks: list[DetailHardlink]
    duplicates: list[DetailDuplicate]


class DetailTrackerEntry(BaseModel):
    media_file_id: int
    season_number: int | None
    episode_number: int | None
    seed_path: str
    client: str
    client_enabled: bool
    state: str
    torrent: str


class DetailTracker(BaseModel):
    """Panoramica per tracker (app/library_detail.py tracker_overview)."""

    tracker_id: int | None  # None = un tracker non configurato, riconosciuto dall'host
    label: str
    configured: bool
    has_upload_profile: bool
    seeding: int  # video del contenuto in seed su questo tracker
    total: int
    entries: list[DetailTrackerEntry]


class DetailSearch(BaseModel):
    tracker: str
    files_searched: int
    last_searched_at: datetime
    next_search_at: datetime | None


class DetailCandidate(BaseModel):
    id: int
    name: str
    tracker: str
    torrent_id_remote: str
    confidence: float
    ambiguity_reason: str | None
    source: str
    direction: str
    videos: int


class DetailSeedJob(BaseModel):
    id: int
    candidate_id: int
    candidate_name: str
    final_status: str
    display_status: str  # "removed" se era in seed ma il torrent non è più nel client
    recheck_status: str | None
    error_message: str | None
    torrent_added_at: datetime | None


class ItemDetailResponse(BaseModel):
    content_type: str
    tmdb_id: int
    title: str | None
    year: int | None
    has_poster: bool
    imdb_id: str | None
    arr_kind: str | None
    arr_url: str | None
    quality: str | None
    total_size_bytes: int
    files: list[DetailFile]
    trackers: list[DetailTracker]
    searches: list[DetailSearch]
    candidates: list[DetailCandidate]
    reviews: list[ReviewResponse]
    seed_jobs: list[DetailSeedJob]


def _content_type_or_404(content_type: str) -> str:
    if content_type not in ("movie", "tv"):
        raise HTTPException(status_code=404, detail=coded_detail("media_item_not_found"))
    return content_type


@router.get("/library/items/{content_type}/{tmdb_id}", response_model=ItemDetailResponse)
def get_item_detail(content_type: str, tmdb_id: int, session: Session = Depends(get_session)):
    """Scheda di dettaglio di un film o di un'intera serie (vista poster)."""
    detail = library_detail.item_detail(session, _content_type_or_404(content_type), tmdb_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=coded_detail("media_item_not_found"))
    detail["reviews"] = [ReviewResponse.from_model(r) for r in detail["reviews"]]
    return detail


class SearchNowResponse(BaseModel):
    files_searched: int
    candidates: int
    rate_limited: bool


@router.post("/library/items/{content_type}/{tmdb_id}/search", response_model=SearchNowResponse)
def search_item_now(content_type: str, tmdb_id: int, session: Session = Depends(get_session)):
    """Cerca subito sui tracker i file orfani di questo contenuto, ignorando
    l'intervallo fra una ricerca e l'altra. Non modifica file né client:
    al massimo crea review, che restano da approvare in Reseeding."""
    _content_type_or_404(content_type)
    if session.query(RunLog).filter(RunLog.finished_at.is_(None)).count():
        raise HTTPException(status_code=409, detail=coded_detail("run_in_progress"))
    mf_ids = {
        mf.id for mf in session.query(MediaFile).join(MediaItem, MediaItem.id == MediaFile.media_item_id)
        .filter(MediaItem.content_type == content_type, MediaItem.tmdb_id == tmdb_id).all()
    }
    if not mf_ids:
        raise HTTPException(status_code=404, detail=coded_detail("media_item_not_found"))
    totals = {"files": 0, "candidates": 0, "rate_limited": False}
    for tracker_row in session.query(Tracker).filter_by(enabled=True).all():
        result = matching.run_media_to_torrent_matching(
            session, tracker_row, adapter_factory.build_tracker_adapter(tracker_row),
            only_media_file_ids=mf_ids, force=True,
        )
        totals["files"] += result["files"]
        totals["candidates"] += result["candidates"]
        totals["rate_limited"] = totals["rate_limited"] or result["rate_limited"]
    return SearchNowResponse(
        files_searched=totals["files"], candidates=totals["candidates"], rate_limited=totals["rate_limited"]
    )


class ExcludeFileRequest(BaseModel):
    relative_path: str
    is_dir: bool = False  # una cartella: tutto quello che c'è dentro


class ExcludeFileResponse(BaseModel):
    pattern: str


def _fnmatch_literal(path: str) -> str:
    """Un pattern che corrisponde solo a quel percorso: i caratteri speciali
    di fnmatch (comuni nei nomi di release, es. "[TbZ]") vanno protetti."""
    return "".join(f"[{ch}]" if ch in "[]*?" else ch for ch in path)


@router.post("/library/exclude", response_model=ExcludeFileResponse)
def exclude_file(body: ExcludeFileRequest, session: Session = Depends(get_session)):
    """Aggiunge ai pattern personalizzati (Configuration > Exclusions) una
    voce che esclude esattamente quel file, o tutto il contenuto di quella
    cartella. Nessun file viene toccato."""
    pattern = _fnmatch_literal(body.relative_path.strip().strip("/"))
    if not pattern:
        raise HTTPException(status_code=400, detail=coded_detail("invalid_path"))
    if body.is_dir:
        pattern = f"{pattern}/*"
    current = settings_repo.get_setting(session, "exclusion_patterns") or ""
    lines = [line for line in current.splitlines() if line.strip()]
    if pattern not in lines:
        lines.append(pattern)
        settings_repo.set_setting(session, "exclusion_patterns", "\n".join(lines))
    return ExcludeFileResponse(pattern=pattern)
