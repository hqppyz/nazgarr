"""Vista "Not imported" (app/not_imported.py): torrent in seed senza hardlink
in libreria, per torrent, con il perché. Sola lettura."""

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import arr, not_imported
from app.api_errors import coded_detail
from app.deps import get_session
from app.library_detail import _host, _quality
from app.models import MediaItem, NotImportedTorrent, RunLog, TorrentClient

router = APIRouter(prefix="/api/torrents", tags=["torrents"])
logger = logging.getLogger(__name__)


class ReplacedBy(BaseModel):
    relative_path: str
    size_bytes: int
    quality: str | None


class NotImportedItem(BaseModel):
    client_torrent_id: int
    name: str
    info_hash: str
    client: str | None
    tracker: str | None
    category: str
    detail: str | None
    matched_by: str | None
    content_type: str | None
    tmdb_id: int | None
    title: str | None
    year: int | None
    season_number: int | None
    episode_number: int | None
    quality: str | None  # del video principale del torrent
    replaced_by: ReplacedBy | None
    total_bytes: int
    video_bytes: int
    file_count: int
    ratio: float | None
    seeding_time_seconds: int | None
    added_at: datetime | None
    state: str
    excluded: bool = False


class CategorySummary(BaseModel):
    count: int
    total_bytes: int


class NotImportedResponse(BaseModel):
    classified: bool  # False finché non è mai stata calcolata
    computed_at: datetime | None = None
    with_arr: bool | None = None  # calcolata con la history di Radarr/Sonarr
    # L'ultima scansione non l'ha ricalcolata (disco o client falliti): i dati sono di prima.
    skipped_at: datetime | None = None
    skipped_reason: str | None = None
    summary: dict[str, CategorySummary]  # solo i torrent non esclusi
    excluded_count: int = 0
    torrents: list[NotImportedItem]


@router.get("/not-imported", response_model=NotImportedResponse)
def list_not_imported(session: Session = Depends(get_session)):
    rows = session.query(NotImportedTorrent).all()
    clients = dict(session.query(TorrentClient.id, TorrentClient.label).all())
    titles: dict[tuple[str, int], tuple[str | None, int | None]] = {}
    for item in session.query(MediaItem).all():
        titles.setdefault((item.content_type, item.tmdb_id), (item.title, item.year))
    summary: dict[str, CategorySummary] = {}
    torrents = []
    for row in rows:
        ct = row.client_torrent
        if not row.excluded:
            entry = summary.setdefault(row.category, CategorySummary(count=0, total_bytes=0))
            entry.count += 1
            entry.total_bytes += row.total_bytes
        title, year = titles.get((row.content_type, row.tmdb_id), (None, None)) if row.tmdb_id else (None, None)
        replaced = row.replaced_by
        torrents.append(NotImportedItem(
            client_torrent_id=ct.id, name=ct.name, info_hash=ct.info_hash, client=clients.get(ct.torrent_client_id),
            tracker=_host(ct.tracker_url), category=row.category, detail=row.detail, matched_by=row.matched_by,
            content_type=row.content_type, tmdb_id=row.tmdb_id, title=title, year=year,
            season_number=row.season_number, episode_number=row.episode_number,
            quality=_quality(os.path.basename(row.main_path)) if row.main_path else None,
            replaced_by=ReplacedBy(
                relative_path=replaced.relative_path, size_bytes=replaced.size_bytes,
                quality=_quality(os.path.basename(replaced.relative_path)),
            ) if replaced else None,
            total_bytes=row.total_bytes, video_bytes=row.video_bytes, file_count=row.file_count,
            ratio=ct.ratio, seeding_time_seconds=ct.seeding_time_seconds, added_at=ct.added_at, state=ct.state,
            excluded=bool(row.excluded),
        ))
    torrents.sort(key=lambda t: t.total_bytes, reverse=True)
    status = not_imported.load_status(session)
    return NotImportedResponse(
        classified=bool(rows) or status.get("computed_at") is not None,
        computed_at=status.get("computed_at"), with_arr=status.get("with_arr"),
        skipped_at=status.get("skipped_at"), skipped_reason=status.get("skipped_reason"),
        summary=summary, excluded_count=sum(1 for r in rows if r.excluded), torrents=torrents,
    )


@router.post("/not-imported/refresh", response_model=NotImportedResponse)
def refresh_not_imported(session: Session = Depends(get_session)):
    """Ricalcola subito, senza aspettare uno scan: rilegge la history di
    Radarr/Sonarr e i dati già indicizzati. Sola lettura su file e client."""
    if session.query(RunLog.id).filter(RunLog.finished_at.is_(None)).first() is not None:
        raise HTTPException(status_code=409, detail=coded_detail("run_in_progress"))
    try:
        arr_index = arr.build_arr_index(session)
    except Exception:
        logger.warning("Radarr/Sonarr non raggiungibili, ricalcolo senza history", exc_info=True)
        arr_index = None
    not_imported.classify_not_imported(session, arr_index if arr_index is not None and len(arr_index) else None)
    return list_not_imported(session=session)
