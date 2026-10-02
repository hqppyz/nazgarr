"""API del flusso di upload v2 (docs/SPEC.md §9 "Upload flow v2"). La
sorgente si sceglie con lo stesso file browser scoped per disco già usato
altrove (nazgarr/fs_scope.py, mai un path assoluto passato dal client); il
lavoro vero lo fa il worker (nazgarr/upload_worker.py), l'API crea i job, li
mostra e registra le decisioni dell'utente ai due punti di approvazione."""

import json
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, object_session

from nazgarr import (
    adapter_factory,
    settings_repo,
    upload_decision,
    upload_file_names,
    upload_identify,
    upload_jobs,
    upload_match_score,
    upload_profiles,
    upload_verify,
)
from nazgarr.adapter_factory import TmdbApiKeyMissingError
from nazgarr.api_errors import coded_detail, from_coded_error
from nazgarr.deps import get_session
from nazgarr.fs_scope import ScopeViolation
from nazgarr.logging_config import safe_error
from nazgarr.models import Disk, TorrentClient, TrackerUploadProfile, UploadEvent, UploadJob, UploadTarget
from nazgarr.upload_jobs import UploadJobError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class ForcedIds(BaseModel):
    tmdb: str | None = None  # "123", "movie/123", "tv/123" o un URL TMDB
    imdb: str | None = None
    tvdb: int | None = None
    mal: int | None = None


class TrackerChoice(BaseModel):
    freeleech: int | None = None  # percentuale scelta alla creazione, tra quelle del profilo


class UploadCreateRequest(BaseModel):
    disk_id: int
    relative_path: str
    tracker_ids: list[int] | None = None  # None = tutti i tracker con un profilo di upload
    forced_ids: ForcedIds | None = None
    overrides: dict | None = None
    tracker_choices: dict[int, TrackerChoice] | None = None


class UploadMatchRequest(BaseModel):
    content_type: str  # movie | tv
    tmdb_id: int
    kind: str  # movie | episode | season_pack | complete_pack
    seasons: list[int] = []
    episode: int | None = None


class UploadOverridesRequest(BaseModel):
    overrides: dict


class TargetDecision(BaseModel):
    target_id: int
    action: str  # upload | reseed | skip
    name: str | None = None
    flags: dict[str, bool | int] | None = None  # freeleech è una percentuale
    category_id: int | None = None
    type_id: int | None = None
    resolution_id: int | None = None
    reseed_torrent_id: str | None = None
    # Nel client: assenti = i default del client, vuoti = nessuno.
    client_category: str | None = None
    client_tags: str | None = None


class UploadApproveRequest(BaseModel):
    targets: list[TargetDecision]


class UploadVerifyRequest(BaseModel):
    torrent_id_remote: str


class UploadReidentifyRequest(BaseModel):
    forced_ids: ForcedIds | None = None


class UploadTargetResponse(BaseModel):
    id: int
    tracker_id: int
    tracker_label: str
    tracker_base_url: str | None  # per i link ai torrent del dupe check (UNIT3D: /torrents/<id>)
    torrent_client_id: int | None
    torrent_client_label: str | None
    status: str
    suggested_action: str | None
    action: str | None
    dupes: list[dict]
    reseed_torrent_id: str | None
    proposed_name: str | None
    approved_name: str | None
    flags: dict
    freeleech_options: list[int]
    category_id: int | None
    type_id: int | None
    resolution_id: int | None
    info_hash: str | None
    torrent_id_remote: str | None
    remote_url: str | None  # pagina del torrent sul tracker (UNIT3D: /torrents/<id>)
    error_message: str | None
    finished_at: datetime | None
    # Le mappe del profilo, per scegliere categoria/tipo/risoluzione a mano.
    category_id_map: dict[str, int]
    type_id_map: dict[str, int]
    resolution_id_map: dict[str, int]
    client_category: str | None = None  # scelti all'approvazione
    client_tags: str | None = None
    client_defaults: dict = {}  # {"category", "tags_upload", "tags_reseed"} dal client del tracker

    @classmethod
    def from_model(cls, t: UploadTarget) -> "UploadTargetResponse":
        profile = object_session(t).get(TrackerUploadProfile, t.tracker_id)
        return cls(
            id=t.id, tracker_id=t.tracker_id, tracker_label=t.tracker.label,
            tracker_base_url=t.tracker.base_url.rstrip("/") if t.tracker.base_url else None,
            torrent_client_id=t.torrent_client_id,
            torrent_client_label=t.torrent_client.label if t.torrent_client else None,
            status=t.status, suggested_action=t.suggested_action, action=t.action,
            dupes=_loads(t.dupes_json, []), reseed_torrent_id=t.reseed_torrent_id,
            proposed_name=t.proposed_name, approved_name=t.approved_name,
            flags=_loads(t.flags_json, {}), freeleech_options=upload_profiles.freeleech_options(profile),
            category_id=t.category_id, type_id=t.type_id,
            resolution_id=t.resolution_id, info_hash=t.info_hash, torrent_id_remote=t.torrent_id_remote,
            remote_url=_remote_url(t),
            error_message=t.error_message, finished_at=t.finished_at,
            category_id_map=_loads(profile.category_id_map_json if profile else None, {}),
            type_id_map=_loads(profile.type_id_map_json if profile else None, {}),
            resolution_id_map=_loads(profile.resolution_id_map_json if profile else None, {}),
            client_category=t.client_category, client_tags=t.client_tags,
            client_defaults=upload_decision.client_label_defaults(t.job, t),
        )


class UploadEventResponse(BaseModel):
    id: int
    target_id: int | None
    created_at: datetime
    level: str
    code: str
    params: dict

    @classmethod
    def from_model(cls, e: UploadEvent) -> "UploadEventResponse":
        return cls(
            id=e.id, target_id=e.target_id, created_at=e.created_at, level=e.level, code=e.code,
            params=_loads(e.params_json, {}),
        )


class UploadJobSummary(BaseModel):
    id: int
    disk_id: int | None
    relative_path: str
    is_dir: bool
    kind: str | None
    status: str
    stage: str | None
    progress_done: int | None
    progress_total: int | None
    queue_position: int | None
    content_type: str | None
    tmdb_id: int | None
    title: str | None
    year: int | None
    poster_path: str | None
    seasons: list[int]
    episode: int | None
    error_message: str | None
    created_at: datetime | None
    finished_at: datetime | None
    targets: list[UploadTargetResponse]
    origin: str | None = None  # "watch": dalla cartella osservata (nazgarr/upload_watch.py)

    @classmethod
    def fields_from(cls, j: UploadJob) -> dict:
        return dict(
            id=j.id, disk_id=j.disk_id, relative_path=j.relative_path, is_dir=j.is_dir, kind=j.kind,
            status=j.status, stage=j.stage, progress_done=j.progress_done, progress_total=j.progress_total,
            queue_position=j.queue_position, content_type=j.content_type, tmdb_id=j.tmdb_id, title=j.title,
            year=j.year, poster_path=j.poster_path, seasons=_loads(j.seasons_json, []), episode=j.episode,
            error_message=j.error_message, created_at=j.created_at, finished_at=j.finished_at,
            targets=[UploadTargetResponse.from_model(t) for t in j.targets], origin=j.origin,
        )

    @classmethod
    def from_model(cls, j: UploadJob) -> "UploadJobSummary":
        return cls(**cls.fields_from(j))


class UploadJobDetail(UploadJobSummary):
    source_path: str
    imdb_id: str | None
    tvdb_id: int | None
    mal_id: int | None
    forced_ids: dict
    overrides: dict
    layout: dict | None
    candidates: list[dict]
    analysis: dict | None
    mediainfo_text: str | None
    screenshot_urls: list[str]
    descriptions: dict[int, str]  # target_id -> descrizione inviata, solo nel dettaglio (è lunga)
    events: list[UploadEventResponse]

    @classmethod
    def from_model(cls, j: UploadJob) -> "UploadJobDetail":
        return cls(
            **cls.fields_from(j),
            source_path=j.source_path, imdb_id=j.imdb_id, tvdb_id=j.tvdb_id, mal_id=j.mal_id,
            forced_ids=_loads(j.forced_ids_json, {}), overrides=_loads(j.overrides_json, {}),
            layout=_loads(j.layout_json, None),
            candidates=upload_match_score.explained(_loads(j.candidates_json, []), _loads(j.layout_json, None)),
            analysis=_loads(j.analysis_json, None), mediainfo_text=j.mediainfo_text,
            screenshot_urls=_loads(j.screenshot_urls_json, []),
            descriptions={t.id: t.description_rendered for t in j.targets if t.description_rendered},
            events=[UploadEventResponse.from_model(e) for e in j.events],
        )


def _remote_url(t: UploadTarget) -> str | None:
    torrent_id = t.torrent_id_remote or (t.reseed_torrent_id if t.action == "reseed" else None)
    if not torrent_id or not t.tracker.base_url:
        return None
    return f"{t.tracker.base_url.rstrip('/')}/torrents/{torrent_id}"


def _loads(raw: str | None, default):
    return json.loads(raw) if raw else default


def _get_job_or_404(session: Session, upload_id: int) -> UploadJob:
    job = session.get(UploadJob, upload_id)
    if job is None:
        raise HTTPException(status_code=404, detail=coded_detail("upload_job_not_found", id=upload_id))
    return job


def _worker(request: Request):
    return request.app.state.upload_worker


@router.get("", response_model=list[UploadJobSummary])
def list_uploads(session: Session = Depends(get_session)):
    jobs = session.query(UploadJob).order_by(UploadJob.id.desc()).all()
    return [UploadJobSummary.from_model(j) for j in jobs]


class QueueOrderRequest(BaseModel):
    job_ids: list[int]


class UploadTrackerResponse(BaseModel):
    id: int
    label: str
    torrent_client_id: int | None  # dove andrà in seed il torrent generato
    torrent_client_label: str | None
    freeleech_options: list[int]
    default_freeleech: int | None


@router.get("/trackers", response_model=list[UploadTrackerResponse])
def list_upload_trackers(session: Session = Depends(get_session)):
    """I tracker selezionabili per un upload (abilitati, con un profilo) e il
    client che userebbero: quello del tracker o, senza, il primo abilitato."""
    out = []
    for tracker in upload_jobs.upload_trackers(session):
        client_id = upload_jobs.default_client_id(session, tracker)
        client = session.get(TorrentClient, client_id) if client_id is not None else None
        profile = session.get(TrackerUploadProfile, tracker.id)
        out.append(UploadTrackerResponse(
            id=tracker.id, label=tracker.label, torrent_client_id=client_id,
            torrent_client_label=client.label if client is not None else None,
            freeleech_options=upload_profiles.freeleech_options(profile),
            default_freeleech=profile.default_freeleech if profile else None,
        ))
    return out


class ImageHostStatusResponse(BaseModel):
    with_api_key: list[str]
    usable: list[str]


class UploadNotice(BaseModel):
    id: int  # l'id dell'evento del job: il frontend ricorda l'ultimo visto
    upload_id: int
    kind: str  # detected | ready
    title: str | None
    year: int | None
    path: str


class UploadNoticesResponse(BaseModel):
    notices: list[UploadNotice]
    latest_id: int  # da qui parte un browser che non ha mai chiesto (niente arretrati)


_NOTICE_CODES = {"job_created": "detected", "analysis_done": "ready"}


@router.get("/notices", response_model=UploadNoticesResponse)
def upload_notices(after: int | None = None, session: Session = Depends(get_session)):
    """Gli avvisi nell'app per le release della cartella osservata: rilevata,
    e pronta per la tua decisione. Solo dopo l'evento `after`; senza, nessun
    arretrato, solo da dove partire."""
    latest = session.query(func.max(UploadEvent.id)).scalar() or 0
    if after is None:
        return UploadNoticesResponse(notices=[], latest_id=latest)
    rows = (
        session.query(UploadEvent, UploadJob)
        .join(UploadJob, UploadJob.id == UploadEvent.job_id)
        .filter(UploadEvent.id > after, UploadEvent.code.in_(_NOTICE_CODES), UploadJob.origin == "watch")
        .order_by(UploadEvent.id)
        .limit(50)
        .all()
    )
    return UploadNoticesResponse(
        notices=[
            UploadNotice(id=event.id, upload_id=job.id, kind=_NOTICE_CODES[event.code], title=job.title,
                         year=job.year, path=job.relative_path)
            for event, job in rows
        ],
        latest_id=latest,
    )


@router.get("/image-hosts", response_model=ImageHostStatusResponse)
def image_host_status(session: Session = Depends(get_session)):
    """Gli host di immagini configurati, per avvisare prima di un upload."""
    return ImageHostStatusResponse(**adapter_factory.image_host_status(session))


class FileNamingRequest(BaseModel):
    rules: dict


@router.get("/file-naming")
def get_file_naming(session: Session = Depends(get_session)) -> dict:
    """Il pattern dei nomi dei file nel torrent (nazgarr/upload_file_names.py):
    quello salvato, e quello di default per tornarci."""
    return {"rules": upload_file_names.rules(session), "default": upload_file_names.DEFAULT_RULES}


@router.put("/file-naming")
def put_file_naming(body: FileNamingRequest, session: Session = Depends(get_session)) -> dict:
    settings_repo.set_setting(session, upload_file_names.SETTING, json.dumps(body.rules))
    return get_file_naming(session)


@router.post("/file-naming/preview")
def preview_file_naming(body: FileNamingRequest, session: Session = Depends(get_session)) -> dict:
    """Le regole in modifica sugli esempi (e sull'ultimo upload), con i nomi
    puliti come diventano i file: niente ":" né accenti, un punto alla volta."""
    preview = upload_decision.preview_names(session, body.rules)
    preview["names"] = {key: upload_file_names.sanitize(name) + ".mkv" for key, name in preview["names"].items()}
    for example in preview.get("examples", []):
        example["name"] = upload_file_names.sanitize(example["name"]) + ".mkv"
    return preview


@router.put("/queue", response_model=list[UploadJobSummary])
def reorder_queue(body: QueueOrderRequest, session: Session = Depends(get_session)):
    """Ordine della coda: il primo parte per primo quando il worker è libero."""
    upload_jobs.reorder_queue(session, body.job_ids)
    jobs = session.query(UploadJob).order_by(UploadJob.id.desc()).all()
    return [UploadJobSummary.from_model(j) for j in jobs]


@router.get("/{upload_id}", response_model=UploadJobDetail)
def get_upload(upload_id: int, session: Session = Depends(get_session)):
    return UploadJobDetail.from_model(_get_job_or_404(session, upload_id))


@router.post("", response_model=UploadJobDetail, status_code=201)
def create_upload(body: UploadCreateRequest, request: Request, session: Session = Depends(get_session)):
    disk = session.get(Disk, body.disk_id)
    if disk is None:
        raise HTTPException(status_code=404, detail=coded_detail("disk_not_found", id=body.disk_id))
    try:
        job = upload_jobs.create_job(
            session, disk, body.relative_path, body.tracker_ids,
            body.forced_ids.model_dump() if body.forced_ids else None, body.overrides,
            {tid: c.model_dump() for tid, c in (body.tracker_choices or {}).items()},
        )
    except (ScopeViolation, UploadJobError) as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    _worker(request).kick(job.id, job.status)
    return UploadJobDetail.from_model(job)


@router.post("/{upload_id}/cancel", response_model=UploadJobDetail)
def cancel_upload(upload_id: int, session: Session = Depends(get_session)):
    job = _get_job_or_404(session, upload_id)
    try:
        upload_jobs.cancel_job(session, job)
    except UploadJobError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    return UploadJobDetail.from_model(job)


@router.delete("/{upload_id}", status_code=204)
def delete_upload(upload_id: int, session: Session = Depends(get_session)):
    job = _get_job_or_404(session, upload_id)
    try:
        upload_jobs.delete_job(session, job)
    except UploadJobError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc


@router.post("/{upload_id}/match", response_model=UploadJobDetail)
def confirm_match(
    upload_id: int, body: UploadMatchRequest, request: Request, session: Session = Depends(get_session)
):
    """Primo punto di approvazione: il contenuto giusto, e per le serie
    stagione ed episodio. Da qui il worker analizza da solo."""
    job = _get_job_or_404(session, upload_id)
    if body.content_type not in ("movie", "tv"):
        raise HTTPException(status_code=400, detail=coded_detail("invalid_content_type", value=body.content_type))
    try:
        details = upload_identify.tmdb_client(session).full_details(body.content_type, body.tmdb_id)
    except TmdbApiKeyMissingError:
        details = None  # solo Radarr/Sonarr: niente dettagli TMDB, bastano gli id
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=coded_detail("tmdb_error", error=safe_error(exc))) from exc
    try:
        upload_jobs.confirm_match(
            session, job, content_type=body.content_type, tmdb_id=body.tmdb_id, kind=body.kind,
            seasons=body.seasons, episode=body.episode, details=details, forced=_loads(job.forced_ids_json, {}),
        )
    except UploadJobError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    _worker(request).kick(job.id, job.status)
    return UploadJobDetail.from_model(job)


@router.post("/{upload_id}/rematch", response_model=UploadJobDetail)
def rematch_upload(upload_id: int, session: Session = Depends(get_session)):
    """Dalla decisione torna al match (nazgarr/upload_jobs.py back_to_match): per
    un match, automatico o no, che si è rivelato sbagliato."""
    job = _get_job_or_404(session, upload_id)
    try:
        upload_jobs.back_to_match(session, job)
    except UploadJobError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    return UploadJobDetail.from_model(job)


@router.post("/{upload_id}/reidentify", response_model=UploadJobDetail)
def reidentify_upload(
    upload_id: int, body: UploadReidentifyRequest, request: Request, session: Session = Depends(get_session)
):
    job = _get_job_or_404(session, upload_id)
    try:
        upload_jobs.reidentify(session, job, body.forced_ids.model_dump() if body.forced_ids else None)
    except UploadJobError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    _worker(request).kick(job.id, job.status)
    return UploadJobDetail.from_model(job)


@router.post("/{upload_id}/targets/{target_id}/verify", response_model=UploadJobDetail)
def verify_target(
    upload_id: int, target_id: int, body: UploadVerifyRequest, request: Request, session: Session = Depends(get_session)
):
    """Full hash check della sorgente contro un torrent già sul tracker, in
    background: se passa, per quel tracker il suggerimento diventa reseed."""
    job = _get_job_or_404(session, upload_id)
    target = next((t for t in job.targets if t.id == target_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=coded_detail("upload_target_not_found", id=target_id))
    try:
        upload_verify.start(session, job, target, body.torrent_id_remote, _worker(request))
    except UploadJobError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    session.refresh(job)
    return UploadJobDetail.from_model(job)


@router.put("/{upload_id}/overrides", response_model=UploadJobDetail)
def update_overrides(upload_id: int, body: UploadOverridesRequest, session: Session = Depends(get_session)):
    """Correzioni ai valori rilevati: rifà nomi e id proposti per ogni tracker."""
    job = _get_job_or_404(session, upload_id)
    try:
        upload_decision.update_overrides(session, job, body.overrides)
    except UploadJobError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    return UploadJobDetail.from_model(job)


@router.post("/{upload_id}/approve", response_model=UploadJobDetail)
def approve_upload(
    upload_id: int, body: UploadApproveRequest, request: Request, session: Session = Depends(get_session)
):
    """Secondo punto di approvazione, la conferma umana obbligatoria di
    docs/SPEC.md §9: da qui il worker porta il job fino in fondo."""
    job = _get_job_or_404(session, upload_id)
    try:
        upload_decision.approve(session, job, [d.model_dump(exclude_unset=True) for d in body.targets])
    except UploadJobError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    _worker(request).kick(job.id, job.status)
    return UploadJobDetail.from_model(job)
