"""Passo 'analyzing' del flusso di upload v2 (docs/SPEC.md §9): dopo il
match confermato, prima dei tracker, tutto quello che si può sapere in
locale. Porta il job al secondo punto di approvazione, awaiting_decision.

1. mediainfo del video principale, una volta sola per tutti i tracker;
2. i client: la sorgente è già in seed? Dall'indice dell'ultima scan
   (client_torrent_file), non con una chiamata a ogni client: stesso inode
   (hardlink, gli stessi byte) o stessa dimensione di un video;
3. Radarr/Sonarr, se configurati: se la history dice che il file è stato
   scaricato da un tracker, non è una release propria dell'utente;
4. per ogni tracker, il dupe check (nazgarr/upload/dupes.py) e l'azione
   suggerita. Un tracker che non risponde non ferma gli altri.
"""

import json
import logging
import os
import threading
import time

from sqlalchemy.orm import Session

from nazgarr.core import events
from nazgarr.core.file_types import is_video
from nazgarr.core.models import (
    ClientTorrent,
    ClientTorrentFile,
    RadarrInstance,
    SeedFile,
    SonarrInstance,
    TorrentClient,
    UploadJob,
)
from nazgarr.integrations import adapter_factory, arr
from nazgarr.library import mediainfo as mediainfo_util
from nazgarr.upload import decision as upload_decision
from nazgarr.upload import dovi_probe
from nazgarr.upload import inventory as upload_inventory
from nazgarr.upload import jobs as upload_jobs
from nazgarr.upload import naming as upload_naming
from nazgarr.upload import pack as upload_pack
from nazgarr.upload.dupes import SourceSummary, check
from nazgarr.upload.naming import dv_profile

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
    """(percorso assoluto, dimensione) dei file che entrano nel torrent:
    sample e spazzatura esclusi, come nell'hashing (nazgarr/upload/inventory.py).
    Il dupe check confronta dimensioni e video con i torrent del tracker:
    contarli falsava il confronto."""
    return [(f.path, f.size) for f in upload_inventory.job_files(job)]


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
            "client_id": torrent.torrent_client_id,
            "client": client.label if client else None,
            "name": torrent.name,
            "info_hash": torrent.info_hash,
            "tracker_host": arr.host_of(torrent.tracker_url),
            "category": torrent.category,
            "state": torrent.state,
            "match": "hardlink" if entry["hardlinked"] else "same_size",
            "videos_matched": len(matched),
            "videos_hardlinked": len(entry["hardlinked"]),
            "videos_total": len(videos),
        })
    matches.sort(key=lambda m: (m["match"] != "hardlink", -m["videos_matched"]))
    return matches


def _arr_grabs(index, files: list[tuple[str, int]]) -> list[dict]:
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


def _strip_video_ext(name: str) -> str:
    base, ext = os.path.splitext(name)
    return base if is_video(name) else name


def name_source(job: UploadJob, files: list[tuple[str, int]], client_matches: list[dict], index) -> dict:
    """Da quale nome leggere risoluzione, sorgente, codec e gruppo per il
    nome della release. Chi parte da un file in libreria ha il nome
    rinominato da Radarr/Sonarr: meglio il nome del torrent che fa già seed
    di quei byte (hardlink), poi il nome originale che Radarr/Sonarr hanno
    registrato, e solo in ultimo il nome della sorgente.

    Per un pack di file scelti a mano (nazgarr/upload/pack.py) gli stessi
    nomi, ma quelli di un episodio: diventano il nome della stagione
    ("Show.S01E01..." -> "Show.S01..."); in ultimo il nome del pack."""
    if upload_pack.is_pack(job):
        found = _single_name_source(job, files, client_matches, index)
        seasons = json.loads(job.seasons_json or "[]")
        if found is None:
            return {"name": upload_pack.name(job), "origin": "source"}
        return {"name": upload_pack.season_name(found["name"], seasons), "fallback": upload_pack.name(job),
                "origin": found["origin"]}
    found = _single_name_source(job, files, client_matches, index)
    if found is not None:
        return found
    source_name = os.path.basename(job.source_path.rstrip(os.sep))
    # Una cartella con un solo contenuto: prima il nome del suo video, la
    # cartella per quello che manca (nazgarr/upload/file_names.py name_detected).
    layout = json.loads(job.layout_json or "{}")
    main = layout.get("main_video")
    if job.is_dir and job.kind in ("movie", "episode") and main:
        return {"name": _strip_video_ext(os.path.basename(main)), "fallback": source_name, "origin": "source"}
    return {"name": source_name, "origin": "source"}


def _single_name_source(job: UploadJob, files: list[tuple[str, int]], client_matches: list[dict], index) -> dict | None:
    hardlinked = next((m for m in client_matches if m["match"] == "hardlink"), None)
    if hardlinked is not None:
        return {"name": _strip_video_ext(hardlinked["name"]), "origin": "hardlink"}
    if index is not None:
        for path, size in sorted(files, key=lambda f: -f[1]):
            if not is_video(path):
                continue
            identity = index.identity_for(path, size)
            if identity is not None and identity.scene_name:
                return {"name": identity.scene_name, "origin": identity.source}
    return None


def summary_of(job: UploadJob, files: list[tuple[str, int]], analysis: dict | None = None) -> SourceSummary:
    """analysis: per leggere i tratti dal nome scelto per la release
    (name_source: il torrent in seed, il nome originale di Radarr/Sonarr) e
    la risoluzione da MediaInfo, invece che dal nome della cartella."""
    analysis = analysis or {}
    video = (analysis.get("mediainfo") or {}).get("video") or {}
    return SourceSummary(
        name=(analysis.get("name_source") or {}).get("name") or upload_pack.name(job),
        resolution=upload_naming.mi_resolution(video) if video else None,
        total_size_bytes=sum(s for _p, s in files),
        video_sizes=tuple(s for p, s in files if is_video(p)),
        kind=job.kind or "movie",
        seasons=frozenset(json.loads(job.seasons_json or "[]")),
        episode=job.episode,
    )


def seeding_here(target, client_matches: list[dict]) -> dict | None:
    """Gli stessi byte (hardlink) sono già in seed sul client di questo
    tracker, con un torrent di questo tracker: niente da fare, né upload né
    reseed."""
    hosts = {arr.host_of(target.tracker.announce_url), arr.host_of(target.tracker.base_url)} - {None}
    for match in client_matches:
        # Tutti i video, non uno: un episodio in seed col suo torrent non
        # mette in seed il pack che lo contiene.
        covers_all = match.get("videos_hardlinked", match["videos_matched"]) >= match["videos_total"]
        if (match["match"] == "hardlink" and covers_all and match["client_id"] == target.torrent_client_id
                and match["tracker_host"] in hosts):
            return match
    return None


def _check_trackers(
    session: Session, job: UploadJob, summary: SourceSummary, client_matches: list[dict]
) -> dict[str, dict]:
    """Dupe check di ogni tracker; restituisce, per target, il torrent che fa
    già seed degli stessi byte sul suo client (vedi seeding_here)."""
    seeding_by_target: dict[str, dict] = {}
    for target in job.targets:
        upload_jobs.set_target_status(target, upload_jobs.TargetStatus.CHECKING)
        session.commit()
        try:
            with adapter_factory.tracker(target.tracker) as adapter:
                found = adapter.search_by_tmdb(job.tmdb_id)
            results, suggested = check(found, summary)
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
        seeding = seeding_here(target, client_matches)
        if seeding is not None:
            seeding_by_target[str(target.id)] = {"name": seeding["name"], "client": seeding["client"]}
            target.suggested_action = "skip"
            upload_jobs.log_event(session, job, "already_seeding_here", level="warning", target=target,
                                  torrent=seeding["name"], client=seeding["client"])
        upload_jobs.set_target_status(target, upload_jobs.TargetStatus.AWAITING_DECISION)
        session.commit()
    return seeding_by_target


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
    # Riepilogo strutturato: anteprima MediaInfo e segnaposto del nome.
    mediainfo_summary = mediainfo_util.extract_summary(main_video)
    # Il Dolby Vision che il contenitore non dichiara, letto dal flusso
    # (nazgarr/upload/dovi_probe.py): solo se MediaInfo non l'ha visto.
    if dovi_probe.complete(mediainfo_summary, main_video):
        upload_jobs.log_event(session, job, "dolby_vision_from_stream", level="warning",
                              profile=dv_profile(mediainfo_summary["video"]) or "?")

    job.stage = "local"
    session.commit()
    index = arr_index_if_configured(session)
    client_matches = _client_matches(session, files)
    analysis = {
        "total_size_bytes": sum(s for _p, s in files),
        "file_count": len(files),
        "client_matches": client_matches,
        "arr_grabs": _arr_grabs(index, files),
        "mediainfo": mediainfo_summary,
        "name_source": name_source(job, files, client_matches, index),
    }
    if upload_pack.is_pack(job):
        job.stage = "pack"
        session.commit()
        analysis["pack_mixed"] = upload_pack.mixed(job)
        if analysis["pack_mixed"]:
            upload_jobs.log_event(session, job, "pack_mixed", level="warning",
                                  fields=", ".join(sorted(analysis["pack_mixed"])))
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
    analysis["seeding_here"] = _check_trackers(session, job, summary_of(job, files, analysis), client_matches)
    job.analysis_json = json.dumps(analysis)
    session.commit()
    upload_decision.propose(session, job)

    if upload_jobs.transition(session, job, "analyzing", "awaiting_decision", stage=None):
        upload_jobs.log_event(session, job, "analysis_done")
        # Per webhook e notifiche: un upload aspetta la tua decisione.
        events.emit(session, "upload.ready", {
            "upload_id": job.id, "title": job.title, "year": job.year, "path": job.relative_path,
            "origin": job.origin, "trackers": [t.tracker.label for t in job.targets],
        })
        session.commit()

