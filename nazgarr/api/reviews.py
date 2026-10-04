"""API della coda di revisione (docs/SPEC.md sezione 8) — approvazione/
rifiuto manuale dei match sotto soglia, retry delle esecuzioni fallite.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, object_session

from nazgarr import pipeline, review, seeding
from nazgarr.api_errors import coded_detail
from nazgarr.deps import get_session
from nazgarr.executor import ExecutionError
from nazgarr.models import Candidate, MatchReview, SeedJob, TorrentClient

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class CandidateFileResponse(BaseModel):
    torrent_path: str
    size_bytes: int | None
    is_video: bool
    local_path: str | None  # relative_path del file locale abbinato, None = mancante
    size_match: bool | None
    mediainfo_match: bool | None
    piece_verified: bool | None


class LayoutSummary(BaseModel):
    """Riepilogo di un torrent multi-file (film con extra, season pack):
    quanti video, quanti verificati coi piece hash, quanti extra dovrà
    scaricare il client perché non presenti in locale."""

    folder: str | None
    video_count: int
    videos_matched: int
    videos_piece_verified: int
    extra_count: int
    extras_missing: int
    extras_missing_bytes: int
    files: list[CandidateFileResponse]


def _layout_summary(c: Candidate) -> LayoutSummary | None:
    if len(c.files) <= 1:
        return None
    files = []
    for f in c.files:
        local = f.media_file or f.seed_file
        files.append(CandidateFileResponse(
            torrent_path=f.torrent_path, size_bytes=f.size_bytes, is_video=f.is_video,
            local_path=local.relative_path if local is not None else None,
            size_match=f.size_match, mediainfo_match=f.mediainfo_match, piece_verified=f.piece_verified,
        ))
    videos = [f for f in files if f.is_video]
    extras_missing = [f for f in files if not f.is_video and f.local_path is None]
    return LayoutSummary(
        folder=c.folder,
        video_count=len(videos),
        videos_matched=sum(1 for f in videos if f.local_path is not None),
        videos_piece_verified=sum(1 for f in videos if f.piece_verified),
        extra_count=len(files) - len(videos),
        extras_missing=len(extras_missing),
        extras_missing_bytes=sum(f.size_bytes or 0 for f in extras_missing),
        files=files,
    )


class SeedJobResponse(BaseModel):
    id: int
    candidate_id: int
    candidate_name: str | None = None
    direction: str | None = None
    tracker: str | None = None
    torrent_client: str | None = None
    final_status: str
    # final_status per l'interfaccia: "removed" se era in seed ma il torrent
    # non è più nel client (review.seed_job_display_status).
    display_status: str | None = None
    recheck_status: str | None
    recheck_skipped: bool = False  # recheck del client saltato: Nazgarr aveva verificato il 100%
    error_message: str | None
    hardlink_created_at: datetime | None = None
    torrent_added_at: datetime | None = None

    @classmethod
    def from_model(cls, sj: SeedJob, in_client: set[str] | None = None) -> "SeedJobResponse":
        candidate = sj.candidate
        session = object_session(sj)
        if in_client is None and session is not None:
            in_client = review.hashes_in_clients(session)
        client = session.get(TorrentClient, sj.torrent_client_id) if session and sj.torrent_client_id else None
        return cls(
            id=sj.id, candidate_id=sj.candidate_id, candidate_name=candidate.name if candidate else None,
            direction=candidate.direction if candidate else None,
            tracker=candidate.tracker.label if candidate and candidate.tracker else None,
            torrent_client=client.label if client else None,
            final_status=sj.final_status,
            display_status=review.seed_job_display_status(sj, in_client or set()),
            recheck_status=sj.recheck_status, recheck_skipped=bool(sj.recheck_skipped),
            error_message=sj.error_message,
            hardlink_created_at=sj.hardlink_created_at, torrent_added_at=sj.torrent_added_at,
        )


class ReviewResponse(BaseModel):
    id: int
    candidate_id: int
    media_item_id: int
    media_file_id: int | None
    seed_file_id: int | None
    status: str
    direction: str
    confidence: float
    candidate_name: str
    ambiguity_reason: str | None
    layout: LayoutSummary | None = None  # solo per torrent con più di un file
    # L'esecuzione partita da questa review (dopo un'approvazione): per il
    # feedback in interfaccia (aggiunto al client, recheck in corso, fallito).
    seed_job: SeedJobResponse | None = None
    # Controllo completo prima dell'esecuzione (verify_before_execute).
    verify_status: str | None = None  # verifying | passed | failed
    verify_detail: str | None = None
    verify_check_id: str | None = None
    # Dove il file è già in seed (tracker o host): non vuoto = un cross-seed.
    seeding_on: list[str] = []

    @classmethod
    def from_model(cls, r: MatchReview) -> "ReviewResponse":
        session = object_session(r)
        seed_job = (
            session.query(SeedJob).filter_by(candidate_id=r.candidate_id).order_by(SeedJob.id.desc()).first()
            if session is not None else None
        )
        return cls(
            id=r.id, candidate_id=r.candidate_id, media_item_id=r.candidate.media_item_id,
            media_file_id=r.media_file_id, seed_file_id=r.seed_file_id,
            status=r.status, direction=r.candidate.direction, confidence=r.candidate.confidence,
            candidate_name=r.candidate.name, ambiguity_reason=r.candidate.ambiguity_reason,
            layout=_layout_summary(r.candidate),
            seed_job=SeedJobResponse.from_model(seed_job) if seed_job is not None else None,
            verify_status=r.verify_status, verify_detail=r.verify_detail, verify_check_id=r.verify_check_id,
            seeding_on=seeding.seeding_on(session, r.media_file_id) if session is not None and r.media_file_id else [],
        )


def _get_review_or_404(session: Session, review_id: int) -> MatchReview:
    row = session.get(MatchReview, review_id)
    if row is None:
        raise HTTPException(status_code=404, detail=coded_detail("review_not_found", id=review_id))
    return row


@router.get("", response_model=list[ReviewResponse])
def list_reviews(session: Session = Depends(get_session)):
    return [ReviewResponse.from_model(r) for r in review.list_ready_for_review(session)]


@router.post("/{review_id}/approve", response_model=ReviewResponse)
def approve_review(review_id: int, request: Request, session: Session = Depends(get_session)):
    """Con la verifica attiva (default) risponde subito con verify_status
    "verifying": approvazione ed esecuzione arrivano a controllo superato,
    l'avanzamento è in /api/full-checks/{verify_check_id}."""
    row = _get_review_or_404(session, review_id)
    try:
        review.request_approval(session, row, request.app.state.session_factory)
    except review.AlreadyVerifyingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ReviewResponse.from_model(row)


@router.post("/{review_id}/reject", response_model=ReviewResponse)
def reject_review(review_id: int, session: Session = Depends(get_session)):
    row = _get_review_or_404(session, review_id)
    review.reject(session, row)
    return ReviewResponse.from_model(row)


class ReconcileResponse(BaseModel):
    reconciled: int
    errors: int


@router.get("/seed-jobs/recent", response_model=list[SeedJobResponse])
def recent_seed_jobs(limit: int = 50, session: Session = Depends(get_session)):
    """Ultime esecuzioni, dalla più recente: l'interfaccia le osserva per
    avvisare quando un recheck in background finisce (seeding o fallito)."""
    rows = session.query(SeedJob).order_by(SeedJob.id.desc()).limit(max(1, min(limit, 200))).all()
    in_client = review.hashes_in_clients(session)
    return [SeedJobResponse.from_model(sj, in_client) for sj in rows]


@router.post("/seed-jobs/reconcile", response_model=ReconcileResponse)
def reconcile_now(session: Session = Depends(get_session)):
    """Controlla subito l'esito dei recheck in attesa (lo scheduler lo fa
    comunque ogni 2 minuti). Sola lettura sul client: nessun torrent
    aggiunto né file modificato."""
    if pipeline.run_in_progress(session):
        raise HTTPException(status_code=409, detail=coded_detail("run_in_progress"))
    return review.reconcile_pending_seed_jobs(session)


@router.get("/failed", response_model=list[SeedJobResponse])
def list_failed(session: Session = Depends(get_session)):
    return [SeedJobResponse.from_model(sj) for sj in review.list_failed_seed_jobs(session)]


@router.post("/failed/{seed_job_id}/retry", response_model=SeedJobResponse)
def retry_failed(seed_job_id: int, session: Session = Depends(get_session)):
    seed_job = session.get(SeedJob, seed_job_id)
    if seed_job is None:
        raise HTTPException(status_code=404, detail=coded_detail("seed_job_not_found", id=seed_job_id))
    try:
        result = review.retry_failed(session, seed_job)
    except ExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SeedJobResponse.from_model(result)


class CandidateAuditResponse(BaseModel):
    id: int
    tracker_id: int
    name: str
    direction: str
    confidence: float
    size_match: bool | None
    mediainfo_match: bool | None
    piece_verified: bool | None
    ambiguity_reason: str | None
    layout: LayoutSummary | None = None


@router.get("/candidates/{media_item_id}", response_model=list[CandidateAuditResponse])
def list_candidates_for_media_item(media_item_id: int, session: Session = Depends(get_session)):
    """Sola lettura, per audit: ogni candidate valutato per un media_item,
    non solo quello scelto per la review (docs/SPEC.md sezione 6)."""
    rows = session.query(Candidate).filter_by(media_item_id=media_item_id).order_by(Candidate.confidence.desc()).all()
    return [
        CandidateAuditResponse(
            id=c.id, tracker_id=c.tracker_id, name=c.name, direction=c.direction,
            confidence=c.confidence, size_match=c.size_match, mediainfo_match=c.mediainfo_match,
            piece_verified=c.piece_verified, ambiguity_reason=c.ambiguity_reason,
            layout=_layout_summary(c),
        )
        for c in rows
    ]
