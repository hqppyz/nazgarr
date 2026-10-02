"""La cartella osservata per le release (decisione dell'utente, 2026-10-02):
ogni file video o cartella nuovo nella cartella "watch" di un disco fa
partire da solo un upload verso i tracker con un profilo di upload, con il
nome del releaser come gruppo e il match TMDB automatico sopra soglia
(nazgarr/upload_identify.py). Arriva fino alla decisione e lì aspetta l'utente:
mai un upload, un hardlink o un torrent senza la sua approvazione.

Un elemento è pronto quando dimensione e data di modifica restano uguali per
STABLE_SECONDS e non ha file parziali dentro (ancora in copia, se no). Ogni
elemento visto è in watch_entry: una release fa partire un solo upload, anche
dopo aver cancellato il suo job. Quello che c'era già quando la cartella è
stata scelta non parte (baseline): si carica a mano se serve.

Il percorso passa sempre da resolve_scoped (nazgarr/fs_scope.py); i link
simbolici non si seguono."""

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from nazgarr import settings_repo, upload_jobs
from nazgarr.file_types import is_video
from nazgarr.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.models import Disk, WatchEntry
from nazgarr.upload_jobs import UploadJobError

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 60
STABLE_SECONDS = 120
RELEASER_SETTING = "upload_releaser_name"
# File ancora in scrittura (download, copia) secondo i client e i programmi più comuni.
PARTIAL_SUFFIXES = (".part", ".!qb", ".!ut", ".tmp", ".crdownload", ".partial", ".filepart")


def releaser_name(session: Session) -> str | None:
    return (settings_repo.get_setting(session, RELEASER_SETTING) or "").strip() or None


def _is_partial(name: str) -> bool:
    return name.lower().endswith(PARTIAL_SUFFIXES)


def _signature(path: str) -> tuple[int, float, bool]:
    """(byte totali, ultima modifica, ha file parziali) di un file o di una cartella."""
    if not os.path.isdir(path):
        st = os.stat(path, follow_symlinks=False)
        return st.st_size, st.st_mtime, _is_partial(path)
    size, mtime, partial = 0, os.stat(path, follow_symlinks=False).st_mtime, False
    for folder, dirs, files in os.walk(path, followlinks=False):
        for name in dirs:
            mtime = max(mtime, os.stat(os.path.join(folder, name), follow_symlinks=False).st_mtime)
        for name in files:
            st = os.stat(os.path.join(folder, name), follow_symlinks=False)
            size += st.st_size
            mtime = max(mtime, st.st_mtime)
            partial = partial or _is_partial(name)
    return size, mtime, partial


def _entries(root: str) -> list[str]:
    """Gli elementi di primo livello: cartelle e file video, niente nascosti né link."""
    out = []
    with os.scandir(root) as listing:
        for entry in listing:
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False) or (entry.is_file(follow_symlinks=False) and is_video(entry.name)):
                out.append(entry.path)
    return sorted(out)


def watch_root(disk: Disk) -> str | None:
    if not disk.watch_rel_path:
        return None
    try:
        root = resolve_scoped(disk.root_path, disk.watch_rel_path)
    except ScopeViolation:
        logger.warning("Cartella osservata fuori dal disco %r: %s", disk.label, disk.watch_rel_path)
        return None
    return root if os.path.isdir(root) else None


def baseline(session: Session, disk: Disk, now: datetime | None = None) -> int:
    """Quando la cartella osservata viene scelta o cambiata: quello che c'è
    già è "visto" e non parte da solo."""
    now = now or datetime.now(UTC)
    session.query(WatchEntry).filter(WatchEntry.disk_id == disk.id).delete(synchronize_session=False)
    root = watch_root(disk)
    count = 0
    for path in _entries(root) if root else []:
        size, mtime, _partial = _signature(path)
        session.add(WatchEntry(
            disk_id=disk.id, relative_path=os.path.relpath(path, disk.root_path), size_bytes=size, mtime=mtime,
            stable_since=now, started_at=now, error_message="present_when_chosen",
        ))
        count += 1
    session.commit()
    return count


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def scan(session: Session, kick: Callable[[int, str], None] | None = None, now: datetime | None = None) -> list[int]:
    """Un giro su tutte le cartelle osservate: gli id dei job creati."""
    now = now or datetime.now(UTC)
    releaser = releaser_name(session)
    created = []
    for disk in session.query(Disk).filter(Disk.watch_rel_path.isnot(None)).all():
        root = watch_root(disk)
        if root is None:
            continue
        known = {row.relative_path: row for row in session.query(WatchEntry).filter(WatchEntry.disk_id == disk.id)}
        present = set()
        for path in _entries(root):
            relative = os.path.relpath(path, disk.root_path)
            present.add(relative)
            try:
                size, mtime, partial = _signature(path)
            except OSError:
                continue  # sparito o illeggibile mentre lo si leggeva: al prossimo giro
            row = known.get(relative)
            if row is None:
                session.add(WatchEntry(disk_id=disk.id, relative_path=relative, size_bytes=size, mtime=mtime,
                                       stable_since=now))
                continue
            if row.started_at is not None:
                continue
            if (row.size_bytes, row.mtime) != (size, mtime) or partial:
                row.size_bytes, row.mtime, row.stable_since = size, mtime, now
                continue
            if size == 0 or now - _as_utc(row.stable_since) < timedelta(seconds=STABLE_SECONDS):
                continue
            session.commit()  # gli elementi nuovi di questo giro restano anche se l'upload non parte
            try:
                job = upload_jobs.create_job(
                    session, disk, relative, overrides={"group": releaser} if releaser else None, origin="watch"
                )
            except UploadJobError as exc:
                if exc.code == "upload_no_trackers":
                    continue  # nessun tracker con un profilo, per ora: si riprova
                session.rollback()
                row = session.get(WatchEntry, row.id)
                row.started_at, row.error_message = now, exc.code
                logger.warning("Cartella osservata: upload di %r non creato (%s)", relative, exc.code)
                continue
            except ScopeViolation:
                session.rollback()
                continue
            row = session.get(WatchEntry, row.id)
            row.job_id, row.started_at = job.id, now
            created.append(job.id)
            logger.info("Cartella osservata: upload #%s avviato per %r", job.id, relative)
            if kick is not None:
                kick(job.id, job.status)
        # Uscito prima di partire (spostato, cancellato): se torna, si riparte da capo.
        for relative, row in known.items():
            if relative not in present and row.started_at is None:
                session.delete(row)
        session.commit()
    return created
