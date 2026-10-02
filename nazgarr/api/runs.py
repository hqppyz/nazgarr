"""Trigger e stato delle run (docs/SPEC.md sezione 11) — scan filesystem
+ indicizzazione client torrent, orchestrati da nazgarr/pipeline.py.

Solo import massivo per ora, innescato manualmente via API e mandato in
background (FastAPI BackgroundTasks — niente scheduler vero, quello
arriva in Fase 5 con APScheduler) così la richiesta HTTP non resta
bloccata per la durata di una run su una libreria grande.
"""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from nazgarr import pipeline
from nazgarr.api_errors import coded_detail
from nazgarr.deps import get_session
from nazgarr.models import RunLog

router = APIRouter(prefix="/api/runs", tags=["runs"])


class PhaseProgressResponse(BaseModel):
    """Una fase della run (nazgarr/run_progress.py): done include gli elementi
    saltati (skipped), così done/total è sempre l'avanzamento vero."""

    status: str  # "running" | "done"
    done: int
    total: int | None
    skipped: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunResponse(BaseModel):
    id: int
    run_type: str
    started_at: datetime
    finished_at: datetime | None
    current_phase: str | None
    phase_total: int | None = None
    phase_done: int | None = None
    phase_detail: str | None = None
    # Solo le fasi già iniziate, nell'ordine della pipeline: quelle assenti
    # sono ancora da fare (o non sono mai partite, se la run è finita).
    phases: dict[str, PhaseProgressResponse] = {}
    items_scanned: int
    matches_found: int = 0
    auto_executed: int = 0
    pending_review: int = 0
    errors: int
    last_error: str | None
    error_messages: list[str] = []  # tutti gli errori della run (last_error è l'ultimo)
    cancel_requested: bool = False  # "Stop run" chiesto, la pipeline si ferma al prossimo aggiornamento
    cancelled: bool = False  # finita perché fermata dall'utente

    @classmethod
    def from_model(cls, run: RunLog) -> "RunResponse":
        try:
            phases = json.loads(run.phases_json) if run.phases_json else {}
        except ValueError:
            phases = {}
        try:
            messages = json.loads(run.errors_json) if run.errors_json else []
        except ValueError:
            messages = []
        if not messages and run.last_error:
            messages = [run.last_error]  # run precedenti a errors_json
        return cls(
            id=run.id, run_type=run.run_type, started_at=run.started_at,
            finished_at=run.finished_at, current_phase=run.current_phase,
            phase_total=run.phase_total, phase_done=run.phase_done, phase_detail=run.phase_detail,
            phases=phases,
            items_scanned=run.items_scanned or 0, matches_found=run.matches_found or 0,
            auto_executed=run.auto_executed or 0, pending_review=run.pending_review or 0,
            errors=run.errors or 0, last_error=run.last_error, error_messages=messages,
            cancel_requested=run.cancel_requested_at is not None,
            cancelled=run.cancel_requested_at is not None and run.finished_at is not None,
        )


def _run_bulk_import_bg(session_factory: sessionmaker, run_id: int, data_dir: str) -> None:
    session = session_factory()
    try:
        run = session.get(RunLog, run_id)
        pipeline.run_bulk_import(session, run, data_dir)
    finally:
        session.close()


@router.post("", response_model=RunResponse, status_code=202)
def trigger_bulk_import(
    request: Request, background_tasks: BackgroundTasks, session: Session = Depends(get_session)
):
    run = pipeline.start_run(session, run_type="bulk_import")
    background_tasks.add_task(
        _run_bulk_import_bg, request.app.state.session_factory, run.id, request.app.state.settings.data_dir
    )
    return RunResponse.from_model(run)


@router.post("/{run_id}/cancel", response_model=RunResponse)
def cancel_run(run_id: int, session: Session = Depends(get_session)):
    """Chiede lo stop di una run in corso: la pipeline lo vede al prossimo
    aggiornamento dell'avanzamento (circa ogni secondo) e si ferma senza
    perdere il lavoro già salvato. Idempotente finché la run è in corso."""
    run = session.get(RunLog, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=coded_detail("run_not_found", id=run_id))
    if run.finished_at is not None:
        raise HTTPException(status_code=409, detail=coded_detail("run_already_finished", id=run_id))
    if run.cancel_requested_at is None:
        run.cancel_requested_at = datetime.now(UTC)
        session.commit()
    return RunResponse.from_model(run)


@router.get("", response_model=list[RunResponse])
def list_runs(session: Session = Depends(get_session)):
    return [RunResponse.from_model(r) for r in session.query(RunLog).order_by(RunLog.id.desc()).all()]


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(RunLog, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=coded_detail("run_not_found", id=run_id))
    return RunResponse.from_model(run)
