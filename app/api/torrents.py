"""Vista "Not imported" (app/not_imported.py): torrent in seed senza hardlink
in libreria, per torrent, con il perché. Sola lettura."""

import os
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_session
from app.library_detail import _host, _quality
from app.models import MediaItem, NotImportedTorrent, RunLog, TorrentClient

router = APIRouter(prefix="/api/torrents", tags=["torrents"])


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


class CategorySummary(BaseModel):
    count: int
    total_bytes: int


class NotImportedResponse(BaseModel):
    classified: bool  # False finché una scansione non l'ha calcolata
    summary: dict[str, CategorySummary]
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
        ))
    torrents.sort(key=lambda t: t.total_bytes, reverse=True)
    # Anche senza risultati una scansione può averla già calcolata: gira alle
    # stesse condizioni della fotografia dei file (app/pipeline.py).
    classified = bool(rows) or session.query(RunLog.id).filter(RunLog.snapshot_saved.is_(True)).first() is not None
    return NotImportedResponse(classified=classified, summary=summary, torrents=torrents)
