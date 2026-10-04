"""Cambiamenti per file fra una scansione e la precedente (Dashboard,
"Changes since last scan"): file nuovi o spariti su disco, e file il cui
stato è cambiato (ora in seed, ora orfano, fermo nel client...).

Alla fine di ogni scansione riuscita lo stato di ogni file (lato libreria e
lato torrent) si confronta con la fotografia della scansione precedente
(file_state_snapshot, una riga per file, sostituita a ogni confronto); le
differenze finiscono in file_change, legate alla run.

Niente confronto (e fotografia invariata) quando i dati non sono affidabili:
- prima scansione: nessuna fotografia precedente, sarebbero tutti "nuovi";
- scansione di un disco o indicizzazione di un client fallita: i file di quel
  disco sembrerebbero spariti, o tutti orfani.

I file esclusi (Configuration > Exclusions) restano nella fotografia ma non
producono mai un cambiamento: escludere un pattern non fa comparire file
"rimossi".
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from nazgarr.core.db_utils import bulk_insert
from nazgarr.core.models import FileChange, FileStateSnapshot, RunLog
from nazgarr.library import states as library
from nazgarr.library.exclusions import load_exclusions

logger = logging.getLogger(__name__)

KEEP_RUNS = 30  # cambiamenti conservati per le ultime N scansioni confrontate


@dataclass(frozen=True)
class _FileState:
    size_bytes: int
    state: str
    stopped: bool
    content_type: str | None
    tmdb_id: int | None


def _current(session: Session) -> dict[tuple[str, int, str], _FileState]:
    states: dict[tuple[str, int, str], _FileState] = {}
    data = library.LibraryData(session)
    for side, rows in (("media", library.media_file_states(session, data=data)),
                       ("torrent", library.seed_file_states(session, data=data))):
        for row in rows:
            states[(side, row["disk_id"], row["relative_path"])] = _FileState(
                size_bytes=row["size_bytes"], state=row["state"], stopped=row.get("stopped", False),
                content_type=row.get("content_type"), tmdb_id=row.get("tmdb_id"),
            )
    return states


def _previous(session: Session) -> dict[tuple[str, int, str], _FileState]:
    return {
        (s.side, s.disk_id, s.relative_path): _FileState(
            size_bytes=s.size_bytes, state=s.state, stopped=bool(s.stopped), content_type=None, tmdb_id=None,
        )
        for s in session.query(FileStateSnapshot).all()
    }


def _save_snapshot(session: Session, run: RunLog, states: dict[tuple[str, int, str], _FileState]) -> None:
    """La fotografia vale per la run che l'ha scattata (snapshot_saved): il
    confronto successivo dice "cambiamenti dal <fine di quella run>"."""
    run.snapshot_saved = True
    session.query(FileStateSnapshot).delete(synchronize_session=False)
    bulk_insert(session, FileStateSnapshot.__table__, [
        {"side": side, "disk_id": disk_id, "relative_path": path, "size_bytes": s.size_bytes,
         "state": s.state, "stopped": s.stopped}
        for (side, disk_id, path), s in states.items()
    ])


def _state_change(before: _FileState, after: _FileState) -> str | None:
    if before.state != after.state:
        return "state"
    if before.stopped != after.stopped:
        return "stopped" if after.stopped else "resumed"
    return None


def record_changes(session: Session, run: RunLog) -> int:
    """Confronta e registra; restituisce quanti cambiamenti. Chiamata dalla
    pipeline solo se scansione e indicizzazione di questa run sono riuscite."""
    current = _current(session)
    has_snapshot = session.query(FileStateSnapshot.id).first() is not None
    if not has_snapshot:
        _save_snapshot(session, run, current)
        session.commit()
        logger.info("Run #%s: prima fotografia dello stato dei file (%d file), nessun confronto", run.id, len(current))
        return 0

    previous = _previous(session)
    exclusions = load_exclusions(session)
    rows = []

    def add(key, change: str, after: _FileState | None, before: _FileState | None) -> None:
        side, disk_id, path = key
        if exclusions.is_excluded(path):
            return
        shown = after or before
        rows.append({
            "run_id": run.id, "side": side, "disk_id": disk_id, "relative_path": path,
            "size_bytes": shown.size_bytes, "change": change,
            "state": after.state if after else None, "previous_state": before.state if before else None,
            "content_type": after.content_type if after else None, "tmdb_id": after.tmdb_id if after else None,
        })

    for key, after in current.items():
        before = previous.get(key)
        if before is None:
            add(key, "added", after, None)
        else:
            change = _state_change(before, after)
            if change:
                add(key, change, after, before)
    for key, before in previous.items():
        if key not in current:
            add(key, "removed", None, before)

    bulk_insert(session, FileChange.__table__, rows)
    _save_snapshot(session, run, current)
    kept_runs = [
        r[0] for r in session.query(FileChange.run_id).distinct().order_by(FileChange.run_id.desc()).all()
    ][:KEEP_RUNS]
    if kept_runs:
        session.query(FileChange).filter(FileChange.run_id < min(kept_runs)).delete(synchronize_session=False)
    session.commit()
    logger.info("Run #%s: %d cambiamenti di file rispetto alla scansione precedente", run.id, len(rows))
    return len(rows)
