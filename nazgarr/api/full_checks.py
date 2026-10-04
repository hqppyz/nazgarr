"""API del controllo completo dei piece hash (nazgarr/reseed/full_check.py): avvio in
background, stato con avanzamento, annullamento. Sola lettura sui file."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.reseed import full_check
from nazgarr.web.deps import get_session

router = APIRouter(prefix="/api/full-checks", tags=["full-checks"])


class FullCheckRequest(BaseModel):
    candidate_id: int
    seed_job_id: int | None = None
    media_file_id: int | None = None


class FileCheckResponse(BaseModel):
    torrent_path: str
    size_bytes: int
    local_path: str | None
    location: str | None
    local_size_bytes: int | None
    pieces: int
    ok: int
    mismatched: int
    unreadable: int
    first_bad_offset: int | None


class CheckResultResponse(BaseModel):
    torrent_name: str
    info_hash: str
    expected_info_hash: str | None
    piece_length: int
    pieces: int
    ok: int
    mismatched: int
    unreadable: int
    percent: float
    bad_pieces: list[int]
    files: list[FileCheckResponse]


class FullCheckResponse(BaseModel):
    id: str
    candidate_id: int
    seed_job_id: int | None
    label: str
    status: str
    bytes_total: int | None
    bytes_done: int
    error: str | None
    result: CheckResultResponse | None
    created_at: datetime
    finished_at: datetime | None
    purpose: str
    review_id: int | None
    stage: str
    verdict: str | None
    verdict_reason: str | None
    execution: str | None
    execution_error: str | None


def _response(state: full_check.CheckState) -> FullCheckResponse:
    return FullCheckResponse(
        id=state.id, candidate_id=state.candidate_id, seed_job_id=state.seed_job_id, label=state.label,
        status=state.status, bytes_total=state.bytes_total, bytes_done=state.bytes_done, error=state.error,
        result=CheckResultResponse(**state.result) if state.result else None,
        created_at=state.created_at, finished_at=state.finished_at, purpose=state.purpose,
        review_id=state.review_id, stage=state.stage, verdict=state.verdict, verdict_reason=state.verdict_reason,
        execution=state.execution, execution_error=state.execution_error,
    )


@router.post("", response_model=FullCheckResponse, status_code=202)
def start_full_check(body: FullCheckRequest, request: Request, session: Session = Depends(get_session)):
    try:
        state = full_check.start_check(
            request.app.state.session_factory, session, body.candidate_id, body.seed_job_id, body.media_file_id
        )
    except full_check.FullCheckError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response(state)


@router.get("", response_model=list[FullCheckResponse])
def list_full_checks():
    return [_response(state) for state in full_check.list_checks()]


@router.get("/{check_id}", response_model=FullCheckResponse)
def get_full_check(check_id: str):
    state = full_check.get_check(check_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Check not found")
    return _response(state)


@router.post("/{check_id}/cancel", response_model=FullCheckResponse)
def cancel_full_check(check_id: str):
    state = full_check.cancel_check(check_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Check not found")
    return _response(state)
