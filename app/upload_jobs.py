"""Flusso di upload v2 (docs/SPEC.md §9 "Upload flow v2"): creazione dei job,
transizioni di stato e registro degli eventi.

Un UploadJob è la sorgente (file o cartella) di un upload verso N tracker,
uno per UploadTarget. Gli stati awaiting_match e awaiting_decision sono i
due soli punti in cui serve l'utente; tutti gli altri li fa avanzare il
worker (app/upload_worker.py), che chiama gli handler di ogni stato.

Le transizioni sono condizionali (UPDATE ... WHERE status = <atteso>): il
worker gira in un altro thread con la sua sessione, e un annullamento
chiesto dall'utente nel frattempo non deve essere sovrascritto dal passo
che il worker stava finendo.
"""

import json
import logging
import os
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api_errors import CodedError
from app.fs_scope import resolve_scoped
from app.models import Disk, TorrentClient, Tracker, TrackerUploadProfile, UploadEvent, UploadJob, UploadTarget

logger = logging.getLogger(__name__)

# Stati in cui il worker ha qualcosa da fare; gli altri aspettano l'utente o
# sono finali.
WORKER_STATES = ("identifying", "analyzing", "queued", "running")
GATE_STATES = ("awaiting_match", "awaiting_decision")
FINAL_STATES = ("done", "partial", "failed", "cancelled")

FORCED_ID_KEYS = ("tmdb", "imdb", "tvdb", "mal")


class UploadJobError(CodedError):
    pass


def log_event(
    session: Session, job: UploadJob, code: str, *, level: str = "info", target: UploadTarget | None = None,
    **params,
) -> UploadEvent:
    event = UploadEvent(
        job_id=job.id, target_id=target.id if target is not None else None, level=level, code=code,
        params_json=json.dumps(params) if params else None,
    )
    session.add(event)
    return event


def transition(session: Session, job: UploadJob, expected: str | tuple[str, ...], new: str, **values) -> bool:
    """Porta il job da uno degli stati attesi a `new`, insieme agli altri
    valori dati. False (e niente scritto) se nel frattempo lo stato è
    cambiato, es. l'utente ha annullato. Fa commit."""
    expected_states = (expected,) if isinstance(expected, str) else expected
    if new in FINAL_STATES and "finished_at" not in values:
        values["finished_at"] = datetime.now(UTC)
    result = session.execute(
        update(UploadJob)
        .where(UploadJob.id == job.id, UploadJob.status.in_(expected_states))
        .values(status=new, **values)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    session.refresh(job)
    return result.rowcount == 1


def default_client_id(session: Session, tracker: Tracker) -> int | None:
    """Il client del tracker se esiste ed è abilitato, altrimenti il primo
    abilitato: la stessa regola del reseeding (app/review.py::_client_for)."""
    if tracker.torrent_client_id is not None:
        row = session.get(TorrentClient, tracker.torrent_client_id)
        if row is not None and row.enabled:
            return row.id
    row = session.query(TorrentClient).filter_by(enabled=True).order_by(TorrentClient.id).first()
    return row.id if row is not None else None


def upload_trackers(session: Session) -> list[Tracker]:
    """I tracker verso cui si può fare upload: abilitati e con un profilo."""
    return (
        session.query(Tracker)
        .join(TrackerUploadProfile, TrackerUploadProfile.tracker_id == Tracker.id)
        .filter(Tracker.enabled.is_(True))
        .order_by(Tracker.id)
        .all()
    )


def _clean_forced_ids(forced_ids: dict | None) -> dict:
    cleaned = {}
    for key in FORCED_ID_KEYS:
        value = (forced_ids or {}).get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        cleaned[key] = value.strip() if isinstance(value, str) else value
    return cleaned


def create_job(
    session: Session,
    disk: Disk,
    relative_path: str,
    tracker_ids: list[int] | None = None,
    forced_ids: dict | None = None,
    overrides: dict | None = None,
) -> UploadJob:
    """Crea il job in 'identifying' (il worker lo prende da lì) con un target
    per tracker. tracker_ids None = tutti i tracker con un profilo di upload.
    Il percorso passa sempre da resolve_scoped (ScopeViolation al chiamante)."""
    source_path = resolve_scoped(disk.root_path, relative_path)
    if not os.path.exists(source_path):
        raise UploadJobError("upload_source_not_found", path=relative_path)
    if source_path == os.path.realpath(disk.root_path):
        raise UploadJobError("upload_source_is_disk_root")

    available = {t.id: t for t in upload_trackers(session)}
    if tracker_ids is None:
        trackers = list(available.values())
    else:
        missing = [tid for tid in tracker_ids if tid not in available]
        if missing:
            raise UploadJobError("upload_tracker_not_available", id=missing[0])
        trackers = [available[tid] for tid in dict.fromkeys(tracker_ids)]
    if not trackers:
        raise UploadJobError("upload_no_trackers")

    job = UploadJob(
        disk_id=disk.id, relative_path=relative_path, source_path=source_path,
        is_dir=os.path.isdir(source_path), status="identifying",
        forced_ids_json=json.dumps(_clean_forced_ids(forced_ids)),
        overrides_json=json.dumps(overrides or {}),
    )
    session.add(job)
    session.flush()
    for tracker in trackers:
        session.add(UploadTarget(
            job_id=job.id, tracker_id=tracker.id, torrent_client_id=default_client_id(session, tracker)
        ))
    log_event(session, job, "job_created", path=relative_path, trackers=[t.label for t in trackers])
    session.commit()
    return job


def cancel_job(session: Session, job: UploadJob) -> None:
    """Annulla un job non ancora finito. Un target già in upload verso il
    tracker non si ferma a metà: il worker lo porta a termine e poi smette
    (vedi app/upload_worker.py)."""
    if job.status in FINAL_STATES:
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    if not transition(session, job, job.status, "cancelled", queue_position=None):
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    log_event(session, job, "job_cancelled")
    session.commit()


def delete_job(session: Session, job: UploadJob) -> None:
    """Solo job fermi (a un punto di approvazione o finiti): uno che il
    worker sta lavorando va prima annullato."""
    if job.status in WORKER_STATES:
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    session.delete(job)
    session.commit()


def next_queue_position(session: Session) -> int:
    last = (
        session.query(UploadJob.queue_position)
        .filter(UploadJob.queue_position.isnot(None))
        .order_by(UploadJob.queue_position.desc())
        .first()
    )
    return (last[0] + 1) if last else 1


def reset_interrupted(session: Session) -> list[int]:
    """All'avvio: i job lasciati a metà da un riavvio. identifying/analyzing/
    queued ripartono da capo (passi senza effetti fuori da Nazgarr). Un job
    'running' torna in coda, ma un target che stava inviando al tracker
    finisce in 'failed': non si sa se il tracker l'ha ricevuto, e ripetere
    l'invio rischierebbe un doppio upload. Restituisce gli id da riprendere."""
    for job in session.query(UploadJob).filter(UploadJob.status == "running").all():
        for target in job.targets:
            if target.status == "uploading":
                target.status = "failed"
                target.error_message = "interrupted"
                log_event(session, job, "target_interrupted", level="error", target=target)
            elif target.status in ("preparing", "verifying"):
                target.status = "approved"
        job.status = "queued"
        job.stage = None
        log_event(session, job, "job_resumed", level="warning")
    session.commit()
    return [
        row.id
        for row in session.query(UploadJob.id)
        .filter(UploadJob.status.in_(WORKER_STATES))
        .order_by(UploadJob.id)
        .all()
    ]


TV_KINDS = ("episode", "season_pack", "complete_pack")


def confirm_match(
    session: Session,
    job: UploadJob,
    *,
    content_type: str,
    tmdb_id: int,
    kind: str,
    seasons: list[int],
    episode: int | None,
    details: dict | None,
    forced: dict,
) -> None:
    """Primo punto di approvazione: l'utente conferma il contenuto (e per le
    serie stagione/episodio). details = full_details di TMDB, None senza
    chiave TMDB. Gli id forzati dall'utente vincono su quelli di TMDB.
    Porta il job in 'analyzing'; il chiamante sveglia il worker."""
    if job.status != "awaiting_match":
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    if content_type == "movie" and kind != "movie":
        raise UploadJobError("upload_kind_mismatch", kind=kind, content_type=content_type)
    if content_type == "tv":
        if kind not in TV_KINDS:
            raise UploadJobError("upload_kind_mismatch", kind=kind, content_type=content_type)
        if not seasons:
            raise UploadJobError("upload_season_required")
        if kind in ("episode", "season_pack") and len(seasons) != 1:
            raise UploadJobError("upload_single_season_required", kind=kind)
        if kind == "episode" and episode is None:
            raise UploadJobError("upload_episode_required")
    if kind in ("season_pack", "complete_pack") and not job.is_dir:
        raise UploadJobError("upload_pack_requires_folder")

    details = details or {}
    values = dict(
        content_type=content_type, tmdb_id=tmdb_id, kind=kind,
        seasons_json=json.dumps(sorted(set(seasons)) if content_type == "tv" else []),
        episode=episode if kind == "episode" else None,
        imdb_id=forced.get("imdb") or details.get("imdb_id"),
        tvdb_id=forced.get("tvdb") or details.get("tvdb_id"),
        mal_id=forced.get("mal"),
    )
    for key in ("title", "year", "poster_path"):
        if details.get(key) is not None:
            values[key] = details[key]
    if not transition(session, job, "awaiting_match", "analyzing", **values):
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    log_event(
        session, job, "match_confirmed", title=job.title, year=job.year, tmdb_id=tmdb_id, kind=kind,
        seasons=json.loads(job.seasons_json or "[]"), episode=job.episode,
    )
    session.commit()


def reidentify(session: Session, job: UploadJob, forced_ids: dict | None) -> None:
    """Rifà l'identificazione con altri id forzati: dal punto di match, o da
    un job fallito mentre identificava."""
    if job.status not in ("awaiting_match", "failed") or (job.status == "failed" and job.tmdb_id is not None):
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    if not transition(
        session, job, job.status, "identifying",
        forced_ids_json=json.dumps(_clean_forced_ids(forced_ids)), error_message=None, finished_at=None,
    ):
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    log_event(session, job, "reidentify_requested")
    session.commit()
