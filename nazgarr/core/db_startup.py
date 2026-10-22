"""L'aggiornamento del database all'avvio, con il backup prima e la modalità
di ripristino se non va (richiesta dell'utente, 2026-10-22).

Prima un passo di migrations.upgrade che falliva usciva dalla lifespan:
supervisord riavviava il processo in loop e l'utente vedeva solo un
traceback nei log. Ora prepare():

1. guarda se l'aggiornamento cambierà qualcosa (db_backup.pending_changes)
   e in quel caso fa il backup (db_backup.take_backup). Se il backup non si
   può fare (spazio, errore di I/O, copia che non passa il controllo) non si
   aggiorna niente. NAZGARR_SKIP_MIGRATION_BACKUP=1 lo salta, con un avviso;
2. aggiorna (migrations.upgrade);
3. se 1 o 2 falliscono scrive <data_dir>/migration-status.json e un ERROR
   nel log (cosa è successo, dov'è il backup, come ripristinarlo; il
   traceback solo nel log) e restituisce lo stato: l'app resta su in
   modalità di ripristino (nazgarr/web/recovery.py), senza scheduler, worker
   né route che toccano il DB;
4. se va tutto bene toglie il migration-status.json di un avvio precedente.

Un riavvio dopo un fallimento, col database ancora quello lasciato a metà
dall'aggiornamento (la stessa impronta: dimensione, mtime, inode, -wal), non
rifà il backup: quello da ripristinare resta quello di prima del primo
tentativo, e qualche riavvio non deve farlo uscire dagli ultimi KEEP."""

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from nazgarr.core import db, db_backup, migrations, settings_repo
from nazgarr.core.config import DB_FILENAME, Settings
from nazgarr.core.logs import redact
from nazgarr.core.version import PROJECT_URL, __version__

logger = logging.getLogger(__name__)

STATUS_FILENAME = "migration-status.json"
# L'ultimo backup prima di un aggiornamento riuscito, per Impostazioni ›
# Applicazione: stato interno (settings_registry.MANAGED_KEYS).
LAST_BACKUP_KEY = "migration_backup_last"
MIGRATION_FAILED = "migration_failed"
BACKUP_FAILED = "backup_failed"
UNREADABLE = "database_unreadable"  # il motivo di un backup fallito perché il DB non si legge
_MAX_ERROR = 300


@dataclass
class Outcome:
    engine: Engine | None = None
    status: dict | None = None  # con un valore: modalità di ripristino
    backup: Path | None = None  # il backup di prima di questo aggiornamento, se c'è
    from_version: int = 0

    @property
    def failed(self) -> bool:
        return self.status is not None


def status_path(data_dir: str | os.PathLike) -> Path:
    return Path(data_dir) / STATUS_FILENAME


def read_status(data_dir: str | os.PathLike) -> dict | None:
    try:
        status = json.loads(status_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return status if isinstance(status, dict) else None


def _write_status(data_dir: str, status: dict) -> None:
    """Scritto accanto e rinominato: mai un file a metà. 0600 come il resto
    della cartella dei dati."""
    target = status_path(data_dir)
    partial = target.with_name(target.name + ".partial")
    try:
        partial.unlink(missing_ok=True)
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2)
            f.write("\n")
        os.replace(partial, target)
    except OSError as exc:  # lo stato c'è comunque nel log e nella pagina
        logger.warning("%s not written: %s", target, exc)


def _clear_status(data_dir: str) -> None:
    path = status_path(data_dir)
    if not path.exists():
        return
    try:
        path.unlink()
        logger.info("Database updated: the failed attempt recorded in %s is resolved, file removed", path)
    except OSError as exc:
        logger.warning("%s not removed: %s", path, exc)


def fingerprint(db_path: str) -> dict | None:
    try:
        st = os.stat(db_path)
    except OSError:
        return None
    try:
        wal = os.path.getsize(db_path + "-wal")
    except OSError:
        wal = 0
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "inode": st.st_ino, "wal": wal}


def short_error(exc: BaseException) -> str:
    """Classe e prima riga del messaggio, per migration-status.json e la
    pagina: senza la query e i parametri che SQLAlchemy aggiunge (possono
    esserci dati), con i segreti dei link tolti (logs.redact), al massimo
    300 caratteri. Il traceback intero resta solo nel log."""
    orig = getattr(exc, "orig", None)  # l'errore di sqlite3 dentro un DBAPIError
    target = orig if isinstance(orig, BaseException) else exc
    message = str(target).split("\n", 1)[0].split("[SQL:", 1)[0].strip()
    text = f"{type(target).__name__}: {message}" if message else type(target).__name__
    return redact(text)[:_MAX_ERROR]


def _reusable_backup(previous: dict | None, current: dict | None) -> Path | None:
    """Il backup di un tentativo fallito, se il database è ancora quello
    lasciato da quel tentativo: ripristinato o usato nel frattempo da
    un'altra versione, l'impronta cambia e serve un backup nuovo."""
    if not previous or previous.get("status") != MIGRATION_FAILED or current is None:
        return None
    backup = previous.get("backup")
    if not isinstance(backup, str) or not Path(backup).is_file():
        return None
    return Path(backup) if previous.get("db_fingerprint") == current else None


def _restore_hint(status: dict) -> str:
    backup = status.get("backup")
    if status["status"] == BACKUP_FAILED and status.get("reason") == UNREADABLE:
        return ("The database cannot be read (it may be damaged) and was not touched. Restore a backup of it: "
                "`nazgarr db backups` lists the ones taken before earlier updates, `nazgarr db restore <file>` puts "
                "one back (also while this page is up).")
    if status["status"] == BACKUP_FAILED:
        return (f"The database was NOT updated and is unchanged. Free some space in {status['backups_dir']} "
                f"(or fix the error above) and restart Nazgarr. To update without a backup (not recommended): "
                f"{db_backup.SKIP_ENV}=1.")
    if not backup:
        return ("No backup was taken before this attempt. Restore your own backup of the database if you have one, "
                f"or report the issue with this log: {PROJECT_URL}/issues")
    return (f"Backup taken before the update: {backup} (database version {status['from_version']}). To go back: "
            f"stop Nazgarr, replace {status['database']} with that backup and delete {DB_FILENAME}-wal and "
            f"{DB_FILENAME}-shm next to it (or run `nazgarr db restore {Path(backup).name}`, also while this page "
            f"is up), then start the version you were using before, or report the issue with this log: "
            f"{PROJECT_URL}/issues")


def _fail(settings: Settings, status: dict, exc: BaseException) -> dict:
    status = {
        "app_version": __version__,
        "failed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "database": settings.db_path,
        "backups_dir": str(db_backup.backups_dir(settings.data_dir)),
        **status,
    }
    _write_status(settings.data_dir, status)
    if status["status"] == BACKUP_FAILED:
        what = (f"The database backup before the update could not be made ({status['reason']}: "
                f"{status['error']}).")
    else:
        step = f"step {status['step']}" if status["step"] is not None else "the step"
        what = f"The database update failed at {step} ({status['step_name']}): {status['error']}."
    logger.error(
        "\n%s\n%s\nNazgarr is in recovery mode: nothing else was started (no scans, no uploads, no changes to "
        "files or torrent clients), and the web UI explains what to do. Status saved in %s.\n%s\n%s",
        "=" * 72, what, status_path(settings.data_dir), _restore_hint(status), "=" * 72, exc_info=exc,
    )
    return status


def prepare(settings: Settings) -> Outcome:
    """Backup e aggiornamento, prima di qualunque altra cosa che usa il DB."""
    db.migrate_legacy_db_filename(settings.data_dir)
    db_path = settings.db_path
    previous = read_status(settings.data_dir)
    current = fingerprint(db_path)  # prima di aprirlo
    pending = db_backup.pending_changes(db_path)
    start, latest = pending.version, migrations.LATEST
    backup: Path | None = None
    if pending.needs_backup:
        if pending.unreadable:
            logger.warning("Database not readable before the update: %s", pending.unreadable)
        folder = db_backup.backups_dir(settings.data_dir)
        backup = _reusable_backup(previous, current)
        if backup is not None:
            logger.info("Backup before the database update: %s (kept from the failed attempt of %s)",
                        backup, previous.get("failed_at") if previous else "?")
        elif db_backup.skip_requested():
            logger.warning("%s is set: updating the database from version %d to %d WITHOUT a backup",
                           db_backup.SKIP_ENV, start, latest)
        else:
            try:
                backup = db_backup.take_backup(db_path, folder, start, latest, __version__)
            except db_backup.BackupError as exc:
                # Un DB che SQLite non legge non si copia: il motivo vero è
                # quello, e la cosa da fare è ripristinare, non liberare spazio.
                reason = UNREADABLE if pending.unreadable and exc.reason == "io_error" else exc.reason
                return Outcome(from_version=start, status=_fail(settings, {
                    "status": BACKUP_FAILED, "from_version": start, "to_version": latest, "step": None,
                    "step_name": "backup", "reason": reason, "error": redact(exc.detail)[:_MAX_ERROR],
                    "backup": None,
                }, exc))
            logger.info("Backup before the database update: %s", backup)
            # Il backup indicato da un fallimento precedente resta comunque.
            kept = (Path(previous["backup"]),) if previous and isinstance(previous.get("backup"), str) else ()
            for old in db_backup.prune(folder, db_backup.keep_count(), protected=kept):
                logger.info("Old database backup removed: %s", old)
    engine = db.make_engine(db_path)
    try:
        migrations.upgrade(engine)
    except migrations.MigrationFailed as exc:
        # Nessuna connessione resta aperta: il ripristino (anche `nazgarr db
        # restore`) può sostituire il file, e l'impronta è quella finale.
        engine.dispose()
        cause = exc.__cause__ or exc
        return Outcome(from_version=start, backup=backup, status=_fail(settings, {
            "status": MIGRATION_FAILED, "from_version": exc.start if exc.start is not None else start,
            "to_version": latest, "step": exc.step, "step_name": exc.name, "error": short_error(cause),
            "backup": str(backup) if backup else None, "db_fingerprint": fingerprint(db_path),
        }, cause))
    _clear_status(settings.data_dir)
    return Outcome(engine=engine, backup=backup, from_version=start)


def record_backup(session: Session, outcome: Outcome) -> None:
    """Dopo un aggiornamento riuscito: il backup di prima, per Impostazioni ›
    Applicazione."""
    if outcome.backup is None:
        return
    parsed = db_backup.parse_name(outcome.backup)
    created = parsed.created_at if parsed else datetime.now(UTC)
    settings_repo.set_setting(session, LAST_BACKUP_KEY, json.dumps({
        "path": str(outcome.backup),
        "from_version": parsed.from_version if parsed else outcome.from_version,
        "to_version": migrations.LATEST,
        "app_version": __version__,
        "created_at": created.isoformat(),
    }))


def last_backup(session: Session) -> dict | None:
    raw = settings_repo.get_setting(session, LAST_BACKUP_KEY)
    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        return None
    return value if isinstance(value, dict) and isinstance(value.get("path"), str) else None
