"""Vista "Not imported" (nazgarr/not_imported.py): torrent in seed senza hardlink
in libreria, per torrent, con il perché. L'unica azione che tocca qualcosa è
la rimozione di un torrent dal client con i suoi file (decisione dell'utente,
2026-10-03): solo su conferma esplicita, solo se il requisito di seed è
soddisfatto e nessun altro torrent usa quei file."""

import logging
import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr import adapter_factory, arr, not_imported, pipeline, seed_requirements
from nazgarr.adapters.torrent_client.base import state_kind
from nazgarr.api_errors import coded_detail
from nazgarr.deps import get_session
from nazgarr.library_detail import _host, _quality
from nazgarr.models import (
    ClientTorrent,
    ClientTorrentFile,
    MediaItem,
    NotImportedTorrent,
    SeedFile,
    SeedJob,
    TorrentClient,
)
from nazgarr.tracker_scope import torrent_host

router = APIRouter(prefix="/api/torrents", tags=["torrents"])
logger = logging.getLogger(__name__)


class ReplacedBy(BaseModel):
    relative_path: str
    size_bytes: int
    quality: str | None


class TorrentSource(BaseModel):
    """Dove sta su disco il contenuto del torrent: la sorgente di un upload."""

    disk_id: int
    relative_path: str
    is_dir: bool


class SeedRequirement(BaseModel):
    status: Literal["unknown_tracker", "no_rules", "met", "pending", "unknown"]
    tracker_id: int | None = None
    tracker_label: str | None = None
    min_seed_time_seconds: int | None = None
    min_ratio: float | None = None
    rule: str | None = None
    remaining: dict[str, float] = {}  # seed_time_seconds e/o ratio che mancano


class RemovalWarning(BaseModel):
    """Un motivo, oltre a seedtime e ratio, per pensarci prima di togliere il
    torrent: code ("shared_files", "client_error", "checking", "downloading")
    e i parametri del messaggio."""

    code: str
    params: dict = {}


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
    source: TorrentSource | None = None  # None se i suoi file non sono nell'indice dell'ultima scan
    # Requisito di seed del tracker e se è soddisfatto (nazgarr/seed_requirements.py).
    seed_requirement: SeedRequirement
    swarm_seeders: int | None = None  # seeder dello sciame secondo il tracker, noi compresi
    removal_warnings: list[RemovalWarning] = []


def _shared_with(session: Session) -> dict[int, list[str]]:
    """Per ogni torrent, gli altri torrent dei client che usano gli stessi
    file (cross-seed, o un altro tracker sugli stessi byte): togliere i dati
    di uno lascerebbe gli altri senza."""
    by_file: dict[int, set[int]] = {}
    for torrent_id, seed_file_id in session.query(ClientTorrentFile.client_torrent_id, ClientTorrentFile.seed_file_id):
        if seed_file_id is not None:
            by_file.setdefault(seed_file_id, set()).add(torrent_id)
    others: dict[int, set[int]] = {}
    for torrents in by_file.values():
        if len(torrents) > 1:
            for torrent_id in torrents:
                others.setdefault(torrent_id, set()).update(torrents - {torrent_id})
    names = dict(session.query(ClientTorrent.id, ClientTorrent.name).filter(
        ClientTorrent.id.in_({o for group in others.values() for o in group})).all()) if others else {}
    return {tid: sorted(names.get(o, "?") for o in group) for tid, group in others.items()}


def removal_warnings(state: str | None, shared: list[str], swarm_seeders: int | None = None) -> list[RemovalWarning]:
    out = []
    # Il tracker dice che nello sciame c'è un solo seeder, noi: togliendolo il
    # torrent muore. Non blocca la rimozione, ma va detto (decisione
    # dell'utente, 2026-10-03).
    if swarm_seeders == 1:
        out.append(RemovalWarning(code="last_seeder", params={}))
    if shared:
        params = {"count": len(shared), "torrents": ", ".join(shared[:3])}
        out.append(RemovalWarning(code="shared_files", params=params))
    # Lo stato nativo ridotto a una categoria: vale per ogni client, non
    # solo per i nomi di qBittorrent.
    kind = state_kind(state)
    if kind == "error":
        out.append(RemovalWarning(code="client_error", params={"state": state}))
    elif kind == "checking":
        out.append(RemovalWarning(code="checking", params={"state": state}))
    elif kind == "downloading":
        out.append(RemovalWarning(code="downloading", params={"state": state}))
    return out


def _sources(session: Session) -> dict[int, TorrentSource]:
    """Per ogni torrent, i suoi file su disco (seed_file): il file se è uno
    solo, altrimenti la cartella che li contiene tutti, sullo stesso disco."""
    rows = (
        session.query(ClientTorrentFile.client_torrent_id, SeedFile.disk_id, SeedFile.relative_path)
        .join(SeedFile, SeedFile.id == ClientTorrentFile.seed_file_id)
        .all()
    )
    by_torrent: dict[int, list[tuple[int, str]]] = {}
    for torrent_id, disk_id, path in rows:
        by_torrent.setdefault(torrent_id, []).append((disk_id, path))
    out = {}
    for torrent_id, files in by_torrent.items():
        if len({d for d, _p in files}) != 1:
            continue
        disk_id = files[0][0]
        if len(files) == 1:
            out[torrent_id] = TorrentSource(disk_id=disk_id, relative_path=files[0][1], is_dir=False)
            continue
        common = os.path.commonpath([p for _d, p in files])
        if common:
            out[torrent_id] = TorrentSource(disk_id=disk_id, relative_path=common, is_dir=True)
    return out


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
    sources = _sources(session)
    requirements = seed_requirements.by_host(session)
    shared = _shared_with(session)
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
            excluded=bool(row.excluded), source=sources.get(ct.id),
            seed_requirement=SeedRequirement(**seed_requirements.evaluate(
                requirements.get(torrent_host(ct.tracker_url)), ct.ratio, ct.seeding_time_seconds,
            )),
            swarm_seeders=ct.swarm_seeders,
            removal_warnings=removal_warnings(ct.state, shared.get(ct.id, []), ct.swarm_seeders),
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
    if pipeline.run_in_progress(session):
        raise HTTPException(status_code=409, detail=coded_detail("run_in_progress"))
    try:
        arr_index = arr.build_arr_index(session)
    except Exception:
        logger.warning("Radarr/Sonarr non raggiungibili, ricalcolo senza history", exc_info=True)
        arr_index = None
    not_imported.classify_not_imported(session, arr_index if arr_index is not None and len(arr_index) else None)
    return list_not_imported(session=session)


# Avvisi che impediscono la rimozione: i file servono ad altri torrent, o il
# client non è in uno stato stabile. "Ultimo seeder" no: si toglie lo stesso,
# ma la conferma lo dice chiaramente.
BLOCKING_WARNINGS = ("shared_files", "client_error", "checking", "downloading")


class RemoveRequest(BaseModel):
    # Va mandato a true: la conferma che i file saranno cancellati.
    delete_files: bool


@router.post("/not-imported/{client_torrent_id}/remove", response_model=NotImportedResponse)
def remove_not_imported(client_torrent_id: int, body: RemoveRequest, session: Session = Depends(get_session)):
    """Toglie il torrent dal suo client e ne cancella i file (lo fa il client).
    Tutti i controlli della vista si rifanno qui: requisito di seed
    soddisfatto, nessun avviso bloccante, client acceso."""
    if not body.delete_files:
        raise HTTPException(status_code=400, detail=coded_detail("removal_not_confirmed"))
    row = session.query(NotImportedTorrent).filter_by(client_torrent_id=client_torrent_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=coded_detail("removal_not_in_not_imported", id=client_torrent_id))
    ct = row.client_torrent
    requirement = seed_requirements.evaluate(
        seed_requirements.by_host(session).get(torrent_host(ct.tracker_url)), ct.ratio, ct.seeding_time_seconds,
    )
    if requirement["status"] != "met":
        raise HTTPException(status_code=400, detail=coded_detail("removal_requirement_not_met",
                                                                 status=requirement["status"]))
    blocking = [w for w in removal_warnings(ct.state, _shared_with(session).get(ct.id, []))
                if w.code in BLOCKING_WARNINGS]
    if blocking:
        raise HTTPException(status_code=400, detail=coded_detail("removal_blocked", reason=blocking[0].code))
    client_row = session.get(TorrentClient, ct.torrent_client_id)
    if client_row is None or not client_row.enabled:
        raise HTTPException(status_code=400, detail=coded_detail("removal_client_unavailable"))
    try:
        adapter_factory.build_torrent_client_adapter(client_row).remove_torrent(ct.info_hash, delete_files=True)
    except Exception as exc:
        logger.warning("Rimozione di %s da %s fallita", ct.name, client_row.label, exc_info=True)
        raise HTTPException(status_code=502, detail=coded_detail("removal_failed", error=str(exc)[:300])) from exc
    logger.info("Torrent %s (%s) rimosso da %s con i suoi file, su richiesta dell'utente",
                ct.name, ct.info_hash, client_row.label)
    # Come per un torrent sparito dal client (nazgarr/torrent_indexer.py):
    # fuori dal DB subito, senza aspettare la prossima scansione.
    session.query(SeedJob).filter(SeedJob.result_client_torrent_id == ct.id).update(
        {SeedJob.result_client_torrent_id: None}, synchronize_session=False)
    session.delete(row)
    session.query(ClientTorrentFile).filter(ClientTorrentFile.client_torrent_id == ct.id).delete(
        synchronize_session=False)
    session.delete(ct)
    session.commit()
    return list_not_imported(session=session)

