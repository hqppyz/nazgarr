"""Flusso di upload v2 (docs/SPEC.md §9 "Upload flow v2"): creazione dei job,
transizioni di stato e registro degli eventi.

Un UploadJob è la sorgente (file o cartella) di un upload verso N tracker,
uno per UploadTarget. Gli stati awaiting_match e awaiting_decision sono i
due soli punti in cui serve l'utente; tutti gli altri li fa avanzare il
worker (nazgarr/upload/worker.py), che chiama gli handler di ogni stato.

Le transizioni sono condizionali (UPDATE ... WHERE status = <atteso>): il
worker gira in un altro thread con la sua sessione, e un annullamento
chiesto dall'utente nel frattempo non deve essere sovrascritto dal passo
che il worker stava finendo.
"""

import json
import logging
import os
import shutil
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from nazgarr.core.errors import CodedError
from nazgarr.core.file_types import is_video
from nazgarr.core.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.core.logs import safe_error
from nazgarr.core.models import (
    UPLOAD_TARGET_STATUSES,
    Disk,
    TorrentClient,
    Tracker,
    TrackerUploadProfile,
    UploadEvent,
    UploadJob,
    UploadTarget,
)
from nazgarr.torrents import client_labels
from nazgarr.upload import inventory as upload_inventory

logger = logging.getLogger(__name__)

# Stati in cui il worker ha qualcosa da fare; gli altri aspettano l'utente o
# sono finali.
WORKER_STATES = ("identifying", "analyzing", "queued", "running")
GATE_STATES = ("awaiting_match", "awaiting_decision")
FINAL_STATES = ("done", "partial", "failed", "cancelled")
# Un target in questi stati lo sta lavorando l'esecuzione (anche di un job
# appena annullato: il tracker in invio si finisce).
BUSY_TARGET_STATES = ("preparing", "uploading", "seeding")

FORCED_ID_KEYS = ("tmdb", "imdb", "tvdb", "mal")


class UploadJobError(CodedError):
    pass


def error_of(exc: BaseException) -> tuple[str, dict]:
    """Il codice e i parametri di un errore, per il registro del job. Solo
    un CodedError li ha davvero: anche un errore di SQLAlchemy ha .code e
    .params, ma sono il codice della sua documentazione ("e3q8") e i
    parametri della query, e params.items() falliva proprio mentre si
    registrava l'errore (audit 2026-10-18)."""
    if isinstance(exc, CodedError):
        return exc.code, dict(exc.params)
    # Il testo va nel registro del job (e nel CLI): un errore di httpx ha
    # l'URL completo, con chiavi e passkey.
    text = safe_error(exc) or type(exc).__name__
    return text, {"error": text}


def error_text(exc: BaseException) -> str:
    return error_of(exc)[0]


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


class TargetStatus(StrEnum):
    """Gli stati di un target (un tracker di un job): gli stessi del CHECK
    del DB (models.UPLOAD_TARGET_STATUSES)."""

    PENDING = "pending"
    CHECKING = "checking"
    AWAITING_DECISION = "awaiting_decision"
    APPROVED = "approved"
    VERIFYING = "verifying"
    PREPARING = "preparing"
    UPLOADING = "uploading"
    SEEDING = "seeding"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


assert {s.value for s in TargetStatus} == set(UPLOAD_TARGET_STATUSES)

_S = TargetStatus
# I passaggi previsti, per leggere il ciclo di vita di un target in un posto
# solo. Uno non previsto non si blocca (ripresa, annullamento e riapertura
# del match hanno percorsi rari) ma si scrive nel log.
EXPECTED_TARGET_TRANSITIONS: dict[TargetStatus, frozenset[TargetStatus]] = {
    _S.PENDING: frozenset({_S.CHECKING, _S.AWAITING_DECISION, _S.FAILED}),
    _S.CHECKING: frozenset({_S.AWAITING_DECISION, _S.FAILED, _S.PENDING}),
    _S.AWAITING_DECISION: frozenset({_S.VERIFYING, _S.APPROVED, _S.SKIPPED, _S.PENDING, _S.CHECKING}),
    _S.VERIFYING: frozenset({_S.AWAITING_DECISION, _S.APPROVED}),
    _S.APPROVED: frozenset({_S.PREPARING, _S.UPLOADING, _S.DONE, _S.FAILED, _S.PENDING}),
    _S.PREPARING: frozenset({_S.UPLOADING, _S.SEEDING, _S.APPROVED, _S.DONE, _S.FAILED}),
    _S.UPLOADING: frozenset({_S.SEEDING, _S.DONE, _S.FAILED}),
    _S.SEEDING: frozenset({_S.DONE, _S.FAILED}),
    _S.DONE: frozenset({_S.PENDING}),
    _S.SKIPPED: frozenset({_S.PENDING, _S.APPROVED}),
    _S.FAILED: frozenset({_S.APPROVED, _S.PENDING}),
}


def set_target_status(target: UploadTarget, status: TargetStatus | str) -> None:
    """L'unico modo di cambiare lo stato di un target: un nome sbagliato
    fallisce subito (ValueError), un passaggio non previsto si vede nel log."""
    new = TargetStatus(status)
    old = target.status
    if old is not None and old != new and new not in EXPECTED_TARGET_TRANSITIONS.get(TargetStatus(old), ()):
        logger.warning("Target %s: passaggio di stato non previsto %s -> %s", target.id, old, new.value)
    target.status = new.value


def transition(
    session: Session, job: UploadJob, expected: str | tuple[str, ...], new: str, emit: bool = True,
    commit: bool = True, **values
) -> bool:
    """Porta il job da uno degli stati attesi a `new`, insieme agli altri
    valori dati. False (e niente scritto) se nel frattempo lo stato è
    cambiato, es. l'utente ha annullato. Fa commit. emit=False: niente
    upload.finished (un job diviso in episodi non è un upload finito).
    commit=False: il commit (o il rollback, se False) lo fa il chiamante,
    insieme al resto della stessa modifica; mai per uno stato finale."""
    expected_states = (expected,) if isinstance(expected, str) else expected
    if new in FINAL_STATES and "finished_at" not in values:
        values["finished_at"] = datetime.now(UTC)
    result = session.execute(
        update(UploadJob)
        .where(UploadJob.id == job.id, UploadJob.status.in_(expected_states))
        .values(status=new, **values)
        .execution_options(synchronize_session=False)
    )
    if not commit:
        assert new not in FINAL_STATES
        if result.rowcount == 1:
            session.refresh(job)
        return result.rowcount == 1
    session.commit()
    session.refresh(job)
    if result.rowcount == 1 and new in FINAL_STATES and emit:
        _emit_finished(session, job)
    return result.rowcount == 1


def _emit_finished(session: Session, job: UploadJob) -> None:
    """upload.finished (nazgarr/core/events.py): la transizione è un UPDATE in blocco,
    che gli hook sul DB non vedono."""
    from nazgarr.core import events

    events.emit(session, "upload.finished", {
        "job_id": job.id, "status": job.status, "title": job.title, "year": job.year,
        "content_type": job.content_type, "tmdb_id": job.tmdb_id,
        "targets": [
            {"tracker": t.tracker.label, "action": t.action, "status": t.status,
             "torrent_id_remote": t.torrent_id_remote, "error": t.error_message}
            for t in job.targets
        ],
    })
    session.commit()


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite restituisce le date senza fuso: sono UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def start_time(when: datetime | None, now: datetime | None = None) -> datetime | None:
    """L'ora di partenza scelta, in UTC; None (subito) se manca o è già passata."""
    when = as_utc(when)
    if when is None or when <= (now or datetime.now(UTC)):
        return None
    return when.astimezone(UTC)


def is_due(job: UploadJob, now: datetime | None = None) -> bool:
    """Un upload programmato parte solo dall'ora scelta (scheduled_at)."""
    return job.scheduled_at is None or as_utc(job.scheduled_at) <= (now or datetime.now(UTC))


def schedule(session: Session, job: UploadJob, when: datetime | None) -> None:
    """Cambia l'ora di partenza di un upload in coda; None o un'ora passata:
    subito. Il chiamante sveglia il worker."""
    if job.status != "queued":
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    job.scheduled_at = start_time(when)
    if job.scheduled_at is None:
        log_event(session, job, "job_start_now")
    else:
        log_event(session, job, "job_scheduled", at=job.scheduled_at.isoformat())
    session.commit()


def default_client_id(session: Session, tracker: Tracker) -> int | None:
    """Il client del tracker se esiste ed è abilitato, altrimenti il primo
    abilitato: la stessa regola del reseeding (nazgarr/reseed/review.py::_client_for)."""
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


def has_symlinks(source_path: str) -> bool:
    if not os.path.isdir(source_path):
        return False
    for dirpath, dirnames, filenames in os.walk(source_path):
        if any(os.path.islink(os.path.join(dirpath, n)) for n in (*dirnames, *filenames)):
            return True
    return False


def create_job(
    session: Session,
    disk: Disk,
    relative_path: str,
    tracker_ids: list[int] | None = None,
    forced_ids: dict | None = None,
    overrides: dict | None = None,
    tracker_choices: dict[int, dict] | None = None,
    origin: str | None = None,
) -> UploadJob:
    """Crea il job in 'identifying' (il worker lo prende da lì) con un target
    per tracker. tracker_ids None = tutti i tracker con un profilo di upload.
    Il percorso passa sempre da resolve_scoped (ScopeViolation al chiamante)."""
    source_path = resolve_scoped(disk.root_path, relative_path)
    if os.path.islink(os.path.join(disk.root_path, relative_path)) or has_symlinks(source_path):
        # Si pubblicherebbe (e si metterebbe in seed) il file a cui punta il link.
        raise UploadJobError("upload_source_has_symlinks", path=relative_path)
    if not os.path.exists(source_path):
        raise UploadJobError("upload_source_not_found", path=relative_path)
    if source_path == os.path.realpath(disk.root_path):
        raise UploadJobError("upload_source_is_disk_root")
    return insert_job(session, disk, relative_path, source_path, os.path.isdir(source_path), tracker_ids,
                      forced_ids, overrides, tracker_choices, origin)


def insert_job(
    session: Session,
    disk: Disk,
    relative_path: str,
    source_path: str,
    is_dir: bool,
    tracker_ids: list[int] | None,
    forced_ids: dict | None,
    overrides: dict | None,
    tracker_choices: dict[int, dict] | None,
    origin: str | None,
    pack_json: str | None = None,
) -> UploadJob:
    """Il job e i suoi target, con la sorgente già controllata dal chiamante
    (create_job, o nazgarr/upload/pack.py per i file scelti a mano)."""
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
        is_dir=is_dir, status="identifying", pack_json=pack_json,
        forced_ids_json=json.dumps(_clean_forced_ids(forced_ids)),
        overrides_json=json.dumps(overrides or {}),
        origin=origin,
    )
    session.add(job)
    session.flush()
    for tracker in trackers:
        choice = (tracker_choices or {}).get(tracker.id) or {}
        # Scelte fatte alla creazione (per ora il freeleech): diventano i flag
        # di partenza del target, i default del profilo completano il resto.
        flags = {"freeleech": int(choice["freeleech"])} if choice.get("freeleech") else None
        session.add(UploadTarget(
            job_id=job.id, tracker_id=tracker.id, torrent_client_id=default_client_id(session, tracker),
            flags_json=json.dumps(flags) if flags else None,
        ))
    log_event(session, job, "job_created", path=relative_path, trackers=[t.label for t in trackers])
    session.commit()
    return job


def _refuse_if_busy(job: UploadJob, active: bool) -> None:
    """Un job annullato può avere ancora un tracker in invio (cancel_job lo
    lascia finire): eliminarlo o riprenderlo adesso lascerebbe un torrent
    pubblicato senza record e senza seed, o due esecuzioni dello stesso job
    (audit 2026-10-18). active: il worker ci sta lavorando adesso."""
    if active or any(t.status in BUSY_TARGET_STATES for t in job.targets):
        raise UploadJobError("upload_job_busy")


def cancel_job(session: Session, job: UploadJob) -> None:
    """Annulla un job non ancora finito. Un target già in upload verso il
    tracker non si ferma a metà: il worker lo porta a termine e poi smette
    (vedi nazgarr/upload/worker.py)."""
    if job.status in FINAL_STATES:
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    previous = job.status
    if not transition(session, job, job.status, "cancelled", queue_position=None):
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    # Da dove riprenderlo (resume_job).
    log_event(session, job, "job_cancelled", previous=previous)
    session.commit()


def _cancelled_from(job: UploadJob) -> str:
    """Lo stato in cui il job è stato annullato: scritto nell'evento, o (per
    i job annullati prima) ricavato da quello che il job ha già."""
    for event in sorted(job.events, key=lambda e: e.id, reverse=True):
        if event.code == "job_cancelled":
            previous = json.loads(event.params_json or "{}").get("previous")
            if previous:
                return previous
            break
    if any(t.status in ("approved", "done") for t in job.targets):
        return "queued"
    if job.analysis_json and job.targets and all(t.status == "awaiting_decision" for t in job.targets):
        return "awaiting_decision"
    return "analyzing" if job.tmdb_id else "identifying"


def require_source(job: UploadJob) -> None:
    """La sorgente ha ancora quello che va nel torrent, non solo la sua
    cartella (audit 2026-10-18): una release della cartella osservata, uscita
    da lì dopo il primo tracker riuscito, lascia la cartella con un sample o
    un nfo, e un nuovo tentativo partiva senza file da caricare (o con il
    torrent fatto dalla copia in seed di un altro tracker). Un file solo
    basta che ci sia; una cartella o un pack devono avere ancora un video."""
    try:
        files = upload_inventory.job_files(job)
    except (OSError, ScopeViolation):
        files = []  # un file del pack sparito, o spostato fuori dal disco
    if not files or (job.is_dir and not any(is_video(f.relative) for f in files)):
        raise UploadJobError("upload_source_missing", path=job.relative_path)


def resume_job(session: Session, job: UploadJob, active: bool = False) -> str:
    """Riprende un job annullato da dove si era fermato: a un punto di
    approvazione ci torna con le scelte fatte, un passo del worker riparte,
    l'esecuzione torna in coda con i soli tracker non ancora fatti (uno già
    pubblicato non si ricarica mai). Restituisce il nuovo stato."""
    if job.status != "cancelled":
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    _refuse_if_busy(job, active)
    if any(event.code == "job_split" for event in job.events):
        raise UploadJobError("upload_job_split")  # continua negli upload degli episodi
    if any(event.code == "job_split_seasons" for event in job.events):
        raise UploadJobError("upload_job_split_seasons")  # continua negli upload delle stagioni
    require_source(job)
    previous = _cancelled_from(job)
    if previous == "running":
        previous = "queued"
    if previous == "queued" and not any(t.status == "approved" for t in job.targets):
        # Nessun tracker rimasto da fare: si torna alla decisione per quelli non pubblicati.
        previous = "analyzing"
    if previous == "analyzing" and any(t.status == "done" for t in job.targets):
        raise UploadJobError("upload_resume_nothing_left")
    values: dict = {"finished_at": None, "stage": None}
    if previous == "queued":
        values["queue_position"] = next_queue_position(session)
    if not transition(session, job, "cancelled", previous, **values):
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    log_event(session, job, "job_resumed_by_user", state=previous)
    session.commit()
    return previous


def retryable_targets(job: UploadJob) -> list[UploadTarget]:
    """I tracker che un nuovo tentativo rifà: falliti, con un upload o un
    reseed da fare, mai pubblicati. Uno pubblicato ma non in seed si
    riprova con "Riprova il seed" (nazgarr/upload/execute.py::retry_seed)."""
    return [t for t in job.targets if t.status == TargetStatus.FAILED and t.action in ("upload", "reseed")
            and not t.torrent_id_remote]


# Gli esiti di un invio di cui non si sa se il tracker l'ha ricevuto: fermato
# da un riavvio, o fallito dopo che la richiesta era partita (un timeout, un
# 5xx, una risposta illeggibile: execute._run_target).
UNSURE_ERRORS = ("interrupted", "upload_outcome_unknown")


def needs_confirmation(target: UploadTarget) -> bool:
    """Non si sa se il tracker l'ha ricevuto, e un nuovo tentativo potrebbe
    pubblicarlo due volte: la ricerca di UNIT3D non elenca i torrent ancora
    in moderazione, quindi nemmeno il dupe check rifatto lo vedrebbe."""
    return target.action == "upload" and target.error_message in UNSURE_ERRORS


def retry_failed(session: Session, job: UploadJob, confirm_interrupted: bool = False,
                 active: bool = False) -> list[UploadTarget]:
    """Un nuovo tentativo dei tracker falliti di un upload finito 'failed' o
    'partial' (richiesta dell'utente, 2026-10-18): un problema temporaneo o
    risolto (il tracker giù, l'image host, i permessi di una cartella) non
    costringe più a ripassare dal match. Le scelte della decisione restano
    tutte (nome, id, flag, reseed, client); il job torna in fondo alla coda,
    e prima dell'invio il dupe check si rifà (execute._recheck_dupes): un
    torrent comparso nel frattempo, anche il nostro di un invio interrotto,
    ferma quel tracker. Un invio interrotto si riprova solo con
    confirm_interrupted. Il chiamante sveglia il worker."""
    if job.status not in ("failed", "partial"):
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    if any(event.code in ("job_split", "job_split_seasons") for event in job.events):
        raise UploadJobError("upload_job_split")
    _refuse_if_busy(job, active)
    require_source(job)
    targets = retryable_targets(job)
    if not targets:
        raise UploadJobError("upload_retry_nothing")
    unsure = [t for t in targets if needs_confirmation(t)]
    if unsure and not confirm_interrupted:
        raise UploadJobError("upload_retry_needs_confirm", trackers=", ".join(t.tracker.label for t in unsure))
    if not transition(
        session, job, ("failed", "partial"), "queued", commit=False, queue_position=next_queue_position(session),
        finished_at=None, stage=None, progress_done=None, progress_total=None, error_message=None, scheduled_at=None,
    ):
        session.rollback()
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    for target in targets:
        set_target_status(target, TargetStatus.APPROVED)
        target.error_message = None
        target.finished_at = None
    log_event(session, job, "job_retried", trackers=", ".join(t.tracker.label for t in targets),
              confirmed=", ".join(t.tracker.label for t in unsure) or None)
    session.commit()
    return targets


def is_retry(job: UploadJob) -> bool:
    """L'esecuzione che sta per partire è un nuovo tentativo (retry_failed),
    non la prima dopo l'approvazione."""
    for event in sorted(job.events, key=lambda e: e.id, reverse=True):
        if event.code == "job_retried":
            return True
        if event.code == "execution_started":
            return False
    return False


def job_folder(data_dir: str, job_id: int) -> str:
    """Dove l'esecuzione tiene i file di un upload: i .torrent (creato, copia
    del tracker, reseed) e gli screenshot."""
    return os.path.join(data_dir, "uploads", str(job_id))


def published_journal(job_dir: str, target_id: int) -> str:
    """Il file in cui l'esecuzione scrive l'id di un torrent appena
    pubblicato, prima del DB (nazgarr/upload/execute.py::run_upload)."""
    return os.path.join(job_dir, f"published-{target_id}.json")


def _journaled_id(data_dir: str | None, job: UploadJob, target: UploadTarget) -> str | None:
    if data_dir is None:
        return None
    try:
        with open(published_journal(job_folder(data_dir, job.id), target.id)) as f:
            value = json.load(f).get("torrent_id_remote")
    except (OSError, ValueError, AttributeError):
        return None
    return str(value) if value else None


def delete_job(session: Session, job: UploadJob, data_dir: str, active: bool = False) -> None:
    """Solo job fermi (a un punto di approvazione o finiti): uno che il
    worker sta lavorando va prima annullato, e uno annullato aspetta che il
    tracker in invio finisca. Con lui va la sua cartella: il client ha già
    la sua copia del .torrent, e SQLite può ridare lo stesso id al prossimo
    upload, che non deve trovarci i file di questo."""
    if job.status in WORKER_STATES:
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    _refuse_if_busy(job, active)
    job_id = job.id
    session.delete(job)
    session.commit()
    shutil.rmtree(job_folder(data_dir, job_id), ignore_errors=True)


def next_queue_position(session: Session) -> int:
    last = (
        session.query(UploadJob.queue_position)
        .filter(UploadJob.queue_position.isnot(None))
        .order_by(UploadJob.queue_position.desc())
        .first()
    )
    return (last[0] + 1) if last else 1


def reset_interrupted(session: Session, data_dir: str | None = None) -> list[int]:
    """All'avvio: i job lasciati a metà da un riavvio. identifying/analyzing/
    queued ripartono da capo (passi senza effetti fuori da Nazgarr). Un job
    'running' torna in coda, ma un target che stava inviando al tracker
    finisce in 'failed': non si sa se il tracker l'ha ricevuto, e ripetere
    l'invio rischierebbe un doppio upload. Restituisce gli id da riprendere.

    Un upload che il tracker aveva già accettato (l'id nel DB, o nel file
    del job scritto prima: execute._journal_published) e uno fermato mentre
    andava nel client ('seeding') sono pubblicati: 'done' con seed_failed,
    da cui si riprova il seed (audit 2026-10-18; prima restavano 'seeding'
    per sempre, senza nessun modo di metterli in seed). Lo stesso per i
    target di un job annullato che il worker stava ancora finendo, o di uno
    finito con un errore che non ha potuto scrivere l'esito dei target (il
    DB non scrivibile)."""
    # Solo i job che girano e quelli con un target ancora "in invio", non tutto lo storico.
    busy = session.query(UploadTarget.job_id).filter(UploadTarget.status.in_(BUSY_TARGET_STATES))
    interrupted = session.query(UploadJob).filter(
        or_(UploadJob.status == "running", UploadJob.id.in_(busy.scalar_subquery()))
    )
    for job in interrupted.all():
        if job.status in GATE_STATES or (job.status in WORKER_STATES and job.status != "running"):
            continue
        for target in job.targets:
            reset_target(session, job, target, data_dir)
        if job.status == "running":
            job.status = "queued"
            job.stage = None
            log_event(session, job, "job_resumed", level="warning")
    # Un full hash check interrotto (in memoria nel worker) non riparte da
    # solo: il target torna alla decisione, l'utente lo rilancia se vuole.
    for target in (
        session.query(UploadTarget)
        .join(UploadJob, UploadJob.id == UploadTarget.job_id)
        .filter(UploadJob.status == "awaiting_decision", UploadTarget.status == "verifying")
        .all()
    ):
        set_target_status(target, TargetStatus.AWAITING_DECISION)
        log_event(session, target.job, "verify_interrupted", level="warning", target=target)
    session.commit()
    return [
        row.id
        for row in session.query(UploadJob.id)
        .filter(UploadJob.status.in_(WORKER_STATES))
        .order_by(UploadJob.id)
        .all()
    ]


def requeue_orphan(session: Session, job: UploadJob, data_dir: str | None) -> bool:
    """Un job 'running' che nessuno esegue più, mentre l'app gira: il passo
    è uscito con un errore che il worker non ha potuto nemmeno registrare
    (il DB non scrivibile). Come al riavvio (reset_interrupted): i target
    in invio si sistemano e il job torna in coda, dove l'esecuzione finisce
    i tracker rimasti e calcola l'esito. Prima finiva 'failed' con "passo
    non disponibile", i target bloccati in invio fino al riavvio (audit
    2026-10-18). False se nel frattempo lo stato è cambiato (annullato)."""
    if not transition(session, job, "running", "queued", commit=False, stage=None):
        session.rollback()
        return False
    for target in job.targets:
        reset_target(session, job, target, data_dir)
    log_event(session, job, "job_resumed", level="warning")
    session.commit()
    return True


def settle_failed_execution(session: Session, job: UploadJob, data_dir: str | None, code: str) -> None:
    """L'esecuzione è uscita con un errore: nessun target resta "in invio"
    (reset_target, come al riavvio), e quelli ancora da fare falliscono con
    lo stesso errore, così "Riprova" li rifà. Il commit lo fa il chiamante,
    insieme allo stato del job."""
    for target in job.targets:
        reset_target(session, job, target, data_dir)
        if target.status == TargetStatus.APPROVED:
            set_target_status(target, TargetStatus.FAILED)
            target.error_message = code
            target.finished_at = datetime.now(UTC)


def outcome(job: UploadJob) -> str:
    """L'esito di un'esecuzione dai suoi target (gli skip non contano)."""
    outcomes = [t.status for t in job.targets if t.action != "skip"]
    if all(s == "done" for s in outcomes):
        return "done"
    if all(s == "failed" for s in outcomes):
        return "failed"
    return "partial"


def reset_target(session: Session, job: UploadJob, target: UploadTarget, data_dir: str | None) -> None:
    """Un target che l'esecuzione ha lasciato in invio (un riavvio, un
    errore): pubblicato -> 'done' con seed_failed, un invio senza esito
    -> 'failed' interrupted, uno appena iniziato torna da fare."""
    published = target.torrent_id_remote or _journaled_id(data_dir, job, target)
    if target.action == "upload" and (target.status == "seeding" or (target.status == "uploading" and published)):
        target.torrent_id_remote = published
        set_target_status(target, TargetStatus.DONE)
        target.error_message = "seed_failed"
        target.finished_at = datetime.now(UTC)
        log_event(session, job, "seed_interrupted", level="error", target=target, torrent=published)
    elif target.status == "uploading":
        set_target_status(target, TargetStatus.FAILED)
        target.error_message = "interrupted"
        target.finished_at = datetime.now(UTC)
        log_event(session, job, "target_interrupted", level="error", target=target)
    elif target.status == "seeding":
        # Un reseed: niente pubblicato. Il client può averlo già: riprovare
        # lo ritrova lì (execute._add_to_client) invece di aggiungerlo due volte.
        set_target_status(target, TargetStatus.FAILED)
        target.error_message = "interrupted"
        target.finished_at = datetime.now(UTC)
        log_event(session, job, "reseed_interrupted", level="error", target=target)
    elif target.status in ("preparing", "verifying"):
        set_target_status(target, TargetStatus.APPROVED)


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
    source_values: dict | None = None,
) -> None:
    """Primo punto di approvazione: l'utente conferma il contenuto (e per le
    serie stagione/episodio). details = full_details di TMDB, None senza
    chiave TMDB. Gli id forzati dall'utente vincono su quelli di TMDB.
    source_values: la sorgente ristretta alle stagioni scelte
    (nazgarr/upload/pack.py season_selection), scritta insieme allo stato.
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
        # Per la categoria anime del client (nazgarr/torrents/client_labels.py).
        anime=client_labels.is_anime(details) if details else None,
    )
    for key in ("title", "year", "poster_path"):
        if details.get(key) is not None:
            values[key] = details[key]
    values.update(source_values or {})
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


def back_to_match(session: Session, job: UploadJob) -> None:
    """Il rollback del match (decisione dell'utente, 2026-10-02): dalla
    decisione si torna a scegliere il contenuto, per un match automatico (o
    manuale) sbagliato. Quello che dipendeva dal match si rifà: analisi,
    nomi proposti, dupe-check. Gli override dell'utente restano. Mai durante
    un full hash check: il suo esito apparterrebbe al match vecchio. Le
    stagioni scelte di una cartella con più stagioni tornano la cartella
    intera, per sceglierne altre."""
    # qui: pack importa questo modulo
    from nazgarr.upload import pack as upload_pack

    if job.status != "awaiting_decision":
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    if any(target.status == "verifying" for target in job.targets):
        raise UploadJobError("upload_verify_in_progress")
    if not transition(session, job, "awaiting_decision", "awaiting_match", analysis_json=None, stage=None,
                      **upload_pack.folder_values(job)):
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    for target in job.targets:
        set_target_status(target, TargetStatus.PENDING)
        target.suggested_action = target.action = None
        target.dupes_json = target.reseed_torrent_id = None
        target.proposed_name = target.approved_name = None
        target.category_id = target.type_id = target.resolution_id = None
    log_event(session, job, "match_reopened", title=job.title, year=job.year)
    session.commit()


def reorder_queue(session: Session, job_ids: list[int]) -> None:
    """Nuovo ordine dei job in coda: prima quelli indicati, nell'ordine dato,
    poi gli altri in coda nell'ordine di prima. Un job non in coda viene
    ignorato (nel frattempo può essere partito)."""
    queued = session.query(UploadJob).filter(UploadJob.status == "queued").order_by(UploadJob.queue_position).all()
    by_id = {job.id: job for job in queued}
    ordered = [by_id[i] for i in dict.fromkeys(job_ids) if i in by_id]
    ordered += [job for job in queued if job not in ordered]
    for position, job in enumerate(ordered, start=1):
        job.queue_position = position
    session.commit()
