"""Dashboard (docs/SPEC.md §10, Fase 5): gauge "salute libreria", KPI
(pending review/falliti/non risolti/orphan_torrent/ignored), storico dello
snapshot di salute per il grafico, cambiamenti per file dall'ultima
scansione (app/file_changes.py).
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import health
from app.deps import get_session
from app.models import FileChange, RunLog

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class LastRunSummary(BaseModel):
    id: int
    run_type: str
    started_at: datetime
    finished_at: datetime | None
    items_scanned: int
    matches_found: int
    auto_executed: int
    pending_review: int
    errors: int


class DashboardResponse(BaseModel):
    health_pct: float
    total_media_size: int
    seeding_media_size: int
    orphan_torrent_count: int
    ignored_count: int
    orphan_torrent_bytes: int = 0
    orphan_not_in_library_bytes: int = 0
    ignored_bytes: int = 0
    duplicate_wasted_bytes: int = 0
    duplicate_files: int = 0
    duplicate_hardlink_groups: int = 0
    pending_review: int
    failed: int
    unmatched: int
    last_run: LastRunSummary | None
    # La scansione precedente all'ultima, per l'andamento delle card
    # (Improving / Worsening): None finché non ce ne sono due.
    previous: "TrendPoint | None" = None


class TrendPoint(BaseModel):
    run_id: int
    finished_at: datetime | None
    health_snapshot: float | None
    orphan_torrent_bytes: int | None
    ignored_bytes: int | None
    duplicate_wasted_bytes: int | None


class HistoryPoint(BaseModel):
    run_id: int
    run_type: str
    finished_at: datetime | None
    health_snapshot: float
    orphan_torrent_bytes: int | None = None
    ignored_bytes: int | None = None
    duplicate_wasted_bytes: int | None = None
    items_scanned: int
    matches_found: int
    auto_executed: int
    pending_review: int
    errors: int


class FileChangeItem(BaseModel):
    side: str  # "media" | "torrent"
    kind: str  # new_media | new_torrent | removed_media | removed_torrent | now_seeding | now_orphaned | ...
    disk_id: int
    relative_path: str
    size_bytes: int
    state: str | None
    previous_state: str | None
    content_type: str | None
    tmdb_id: int | None


class ChangesResponse(BaseModel):
    run_id: int | None  # la scansione che ha rilevato i cambiamenti
    since: datetime | None  # fine della scansione precedente con cui si è confrontato
    until: datetime | None
    baseline_only: bool  # c'è solo la prima fotografia: nessun confronto ancora
    health_delta: float | None  # punti di salute rispetto alla scansione precedente
    total: int
    counts: dict[str, int]
    changes: list[FileChangeItem]  # al massimo `limit`, i conteggi valgono per tutti


def _kind(change: FileChange) -> str:
    if change.change == "added":
        return f"new_{change.side}"
    if change.change == "removed":
        return f"removed_{change.side}"
    if change.change in ("stopped", "resumed"):
        return change.change
    if change.state == "seeding":
        return "now_seeding"
    if (change.state or "").startswith("orphan"):
        return "now_orphaned"
    if change.state == "ignored":
        return "now_ignored"
    return "state_changed"


def _last_run_summary(session: Session) -> LastRunSummary | None:
    run = session.query(RunLog).filter(RunLog.finished_at.isnot(None)).order_by(RunLog.id.desc()).first()
    if run is None:
        return None
    return LastRunSummary(
        id=run.id, run_type=run.run_type, started_at=run.started_at, finished_at=run.finished_at,
        items_scanned=run.items_scanned, matches_found=run.matches_found, auto_executed=run.auto_executed,
        pending_review=run.pending_review, errors=run.errors,
    )


@router.get("", response_model=DashboardResponse)
def get_dashboard(disk_id: int | None = None, session: Session = Depends(get_session)):
    snapshot = health.compute_snapshot(session, disk_id=disk_id)
    finished = (
        session.query(RunLog).filter(RunLog.finished_at.isnot(None), RunLog.health_snapshot.isnot(None))
        .order_by(RunLog.id.desc()).limit(2).all()
    )
    previous = finished[1] if len(finished) > 1 else None
    return DashboardResponse(
        **snapshot, last_run=_last_run_summary(session),
        previous=TrendPoint(
            run_id=previous.id, finished_at=previous.finished_at, health_snapshot=previous.health_snapshot,
            orphan_torrent_bytes=previous.orphan_torrent_bytes, ignored_bytes=previous.ignored_bytes,
            duplicate_wasted_bytes=previous.duplicate_wasted_bytes,
        ) if previous else None,
    )


@router.get("/history", response_model=list[HistoryPoint])
def get_history(limit: int = 30, days: int | None = None, session: Session = Depends(get_session)):
    """Dalla più recente. `days`: solo le scansioni finite negli ultimi N
    giorni (finestra 7d/30d/90d della dashboard), fino a 1000; senza, le
    ultime `limit`."""
    query = session.query(RunLog).filter(RunLog.health_snapshot.isnot(None))
    if days is not None:
        query = query.filter(RunLog.finished_at >= datetime.now(UTC) - timedelta(days=days))
        limit = 1000
    runs = query.order_by(RunLog.id.desc()).limit(limit).all()
    return [
        HistoryPoint(
            run_id=r.id, run_type=r.run_type, finished_at=r.finished_at, health_snapshot=r.health_snapshot,
            orphan_torrent_bytes=r.orphan_torrent_bytes, ignored_bytes=r.ignored_bytes,
            duplicate_wasted_bytes=r.duplicate_wasted_bytes,
            items_scanned=r.items_scanned, matches_found=r.matches_found, auto_executed=r.auto_executed,
            pending_review=r.pending_review, errors=r.errors,
        )
        for r in runs
    ]


@router.get("/changes", response_model=ChangesResponse)
def get_changes(limit: int = 1000, session: Session = Depends(get_session)):
    """Cambiamenti per file dell'ultima scansione confrontata con la
    precedente (app/file_changes.py): file nuovi, spariti, cambiati di stato."""
    snapshots = (
        session.query(RunLog).filter(RunLog.snapshot_saved.is_(True)).order_by(RunLog.id.desc()).limit(2).all()
    )
    if len(snapshots) < 2:
        latest = snapshots[0] if snapshots else None
        return ChangesResponse(
            run_id=latest.id if latest else None, since=None, until=latest.finished_at if latest else None,
            baseline_only=latest is not None, health_delta=None, total=0, counts={}, changes=[],
        )
    current, previous = snapshots
    rows = session.query(FileChange).filter_by(run_id=current.id).order_by(FileChange.id).all()
    counts: dict[str, int] = {}
    items = []
    for row in rows:
        kind = _kind(row)
        counts[kind] = counts.get(kind, 0) + 1
        if len(items) < max(1, min(limit, 5000)):
            items.append(FileChangeItem(
                side=row.side, kind=kind, disk_id=row.disk_id, relative_path=row.relative_path,
                size_bytes=row.size_bytes, state=row.state, previous_state=row.previous_state,
                content_type=row.content_type, tmdb_id=row.tmdb_id,
            ))
    delta = (
        current.health_snapshot - previous.health_snapshot
        if current.health_snapshot is not None and previous.health_snapshot is not None else None
    )
    return ChangesResponse(
        run_id=current.id, since=previous.finished_at, until=current.finished_at, baseline_only=False,
        health_delta=delta, total=len(rows), counts=counts, changes=items,
    )
