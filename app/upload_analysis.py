"""Passo 'analyzing' del flusso di upload v2 (docs/SPEC.md §9): dopo il
match confermato, prima dei tracker, tutto quello che si può sapere in
locale. Porta il job al secondo punto di approvazione, awaiting_decision.

1. mediainfo del video principale, una volta sola per tutti i tracker;
2. i client: la sorgente è già in seed? Dall'indice dell'ultima scan
   (client_torrent_file), non con una chiamata a ogni client: stesso inode
   (hardlink, gli stessi byte) o stessa dimensione di un video;
3. Radarr/Sonarr, se configurati: se la history dice che il file è stato
   scaricato da un tracker, non è una release propria dell'utente;
4. per ogni tracker, il dupe check (app/upload_dupes.py) e l'azione
   suggerita. Un tracker che non risponde non ferma gli altri.
"""

import json
import logging
import os
import threading
import time

from sqlalchemy.orm import Session

from app import adapter_factory, arr, mediainfo_util, upload_decision, upload_jobs
from app.file_types import is_video
from app.models import (
    ClientTorrent,
    ClientTorrentFile,
    RadarrInstance,
    SeedFile,
    SonarrInstance,
    TorrentClient,
    UploadJob,
)
from app.upload_dupes import SourceSummary, check

logger = logging.getLogger(__name__)

# Un video più piccolo di così non dice niente se ha la stessa dimensione
# di un altro (sample, extra): non conta per il confronto con i client.
MIN_MATCH_BYTES = 50 * 1024 * 1024

# L'indice Radarr/Sonarr legge tutta la history: costruito una volta ogni
# tanto, non per ogni upload in coda.
ARR_INDEX_TTL_SECONDS = 600
_arr_cache: tuple[float, arr.ArrIndex] | None = None
_arr_lock = threading.Lock()


def arr_index(session: Session) -> arr.ArrIndex:
    global _arr_cache
    with _arr_lock:
        if _arr_cache is not None and time.monotonic() - _arr_cache[0] < ARR_INDEX_TTL_SECONDS:
            return _arr_cache[1]
    index = arr.build_arr_index(session)
    with _arr_lock:
        _arr_cache = (time.monotonic(), index)
    return index


def arr_index_if_configured(session: Session) -> arr.ArrIndex | None:
    """L'indice solo se c'è almeno un'istanza abilitata; None anche se non
    si riesce a costruirlo: Radarr/Sonarr restano sempre opzionali."""
    enabled = sum(session.query(m).filter_by(enabled=True).count() for m in (RadarrInstance, SonarrInstance))
    if enabled == 0:
        return None
    try:
        return arr_index(session)
    except Exception:
        logger.warning("Indice Radarr/Sonarr non disponibile per l'upload", exc_info=True)
        return None


def source_files(job: UploadJob) -> list[tuple[str, int]]:
    """(percorso assoluto, dimensione) di ogni file della sorgente."""
    if not job.is_dir:
        return [(job.source_path, os.path.getsize(job.source_path))]
    out = []
    for dirpath, dirnames, filenames in os.walk(job.source_path):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if os.path.isfile(path):
                out.append((path, os.path.getsize(path)))
    return out


def _client_matches(session: Session, files: list[tuple[str, int]]) -> list[dict]:
    videos = [(p, s) for p, s in files if is_video(p) and s >= MIN_MATCH_BYTES]
    if not videos:
        return []
    by_torrent: dict[int, dict] = {}

    # Stessi byte sul disco: un file della sorgente è hardlink di un file in seed.
    for path, _size in videos:
        st = os.stat(path)
        rows = (
            session.query(ClientTorrentFile.client_torrent_id)
            .join(SeedFile, SeedFile.id == ClientTorrentFile.seed_file_id)
            .filter(SeedFile.st_dev == st.st_dev, SeedFile.inode == st.st_ino)
            .all()
        )
        for (torrent_id,) in rows:
            entry = by_torrent.setdefault(torrent_id, {"hardlinked": set(), "same_size": set()})
            entry["hardlinked"].add(path)

    sizes = {s for _p, s in videos}
    rows = (
        session.query(ClientTorrentFile.client_torrent_id, ClientTorrentFile.size_bytes)
        .filter(ClientTorrentFile.size_bytes.in_(sizes))
        .all()
    )
    for torrent_id, size in rows:
        entry = by_torrent.setdefault(torrent_id, {"hardlinked": set(), "same_size": set()})
        entry["same_size"].update(p for p, s in videos if s == size)

    matches = []
    for torrent_id, entry in by_torrent.items():
        torrent = session.get(ClientTorrent, torrent_id)
        client = session.get(TorrentClient, torrent.torrent_client_id)
        matched = entry["hardlinked"] | entry["same_size"]
        matches.append({
            "client": client.label if client else None,
            "name": torrent.name,
            "info_hash": torrent.info_hash,
            "tracker_host": arr.host_of(torrent.tracker_url),
            "category": torrent.category,
            "state": torrent.state,
            "match": "hardlink" if entry["hardlinked"] else "same_size",
            "videos_matched": len(matched),
            "videos_total": len(videos),
        })
    matches.sort(key=lambda m: (m["match"] != "hardlink", -m["videos_matched"]))
    return matches


def _arr_grabs(session: Session, files: list[tuple[str, int]]) -> list[dict]:
    index = arr_index_if_configured(session)
    if index is None:
        return []
    grabs, seen = [], set()
    for path, size in files:
        if not is_video(path):
            continue
        grab = index.grab_for(path, size)
        if grab is None:
            # Il file importato in libreria: la history conosce il percorso di
            # download, non quello in libreria. Nessun modo affidabile da qui.
            continue
        key = (grab.tracker_host, grab.torrent_id_remote)
        if key not in seen:
            seen.add(key)
            grabs.append({
                "tracker_host": grab.tracker_host, "torrent_id_remote": grab.torrent_id_remote,
                "info_hash": grab.info_hash, "indexer": grab.indexer,
            })
    return grabs


def summary_of(job: UploadJob, files: list[tuple[str, int]]) -> SourceSummary:
    return SourceSummary(
        name=os.path.basename(job.source_path.rstrip(os.sep)),
        total_size_bytes=sum(s for _p, s in files),
        video_sizes=tuple(s for p, s in files if is_video(p)),
        kind=job.kind or "movie",
        seasons=frozenset(json.loads(job.seasons_json or "[]")),
        episode=job.episode,
    )


def _check_trackers(session: Session, job: UploadJob, summary: SourceSummary) -> None:
    for target in job.targets:
        target.status = "checking"
        session.commit()
        try:
            adapter = adapter_factory.build_tracker_adapter(target.tracker)
            results, suggested = check(adapter.search_by_tmdb(job.tmdb_id), summary)
        except Exception as exc:
            # L'utente decide lo stesso: senza dupe check, ma lo sa.
            logger.warning("Dupe check fallito su %s", target.tracker.label, exc_info=True)
            target.dupes_json = None
            target.suggested_action = None
            target.error_message = "dupe_check_failed"
            upload_jobs.log_event(session, job, "dupe_check_failed", level="warning", target=target, error=str(exc))
        else:
            target.dupes_json = json.dumps(results)
            target.suggested_action = suggested
            target.error_message = None
            counts = {v: sum(1 for r in results if r["verdict"] == v) for v in ("identical", "same_slot")}
            upload_jobs.log_event(
                session, job, "dupe_check_done", target=target, results=len(results),
                identical=counts["identical"], same_slot=counts["same_slot"], suggested=suggested,
            )
        target.status = "awaiting_decision"
        session.commit()


def handle(session: Session, job: UploadJob, worker) -> None:
    upload_jobs.log_event(session, job, "analysis_started")
    session.commit()
    try:
        files = source_files(job)
    except OSError as exc:
        raise upload_jobs.UploadJobError("upload_source_unreadable", error=str(exc)) from exc
    layout = json.loads(job.layout_json or "{}")
    main_video = layout.get("main_video") or job.source_path

    job.stage = "mediainfo"
    session.commit()
    try:
        job.mediainfo_text = mediainfo_util.extract_full_text(main_video)
    except Exception:
        logger.warning("mediainfo fallito per %r", main_video, exc_info=True)
        upload_jobs.log_event(session, job, "mediainfo_failed", level="warning")

    job.stage = "local"
    session.commit()
    analysis = {
        "total_size_bytes": sum(s for _p, s in files),
        "file_count": len(files),
        "client_matches": _client_matches(session, files),
        "arr_grabs": _arr_grabs(session, files),
    }
    job.analysis_json = json.dumps(analysis)
    if analysis["client_matches"]:
        upload_jobs.log_event(session, job, "already_on_client", level="warning", count=len(analysis["client_matches"]))
    if analysis["arr_grabs"]:
        upload_jobs.log_event(
            session, job, "grabbed_from_tracker", level="warning",
            trackers=[g["tracker_host"] for g in analysis["arr_grabs"]],
        )
    session.commit()

    job.stage = "trackers"
    session.commit()
    _check_trackers(session, job, summary_of(job, files))
    upload_decision.propose(session, job)

    if upload_jobs.transition(session, job, "analyzing", "awaiting_decision", stage=None):
        upload_jobs.log_event(session, job, "analysis_done")
        session.commit()

