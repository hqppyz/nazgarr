"""L'aggiornamento del database all'avvio, con il backup prima e la modalità
di ripristino se non va (richiesta dell'utente, 2026-10-22).

Prima un passo di migrations.upgrade che falliva usciva dalla lifespan:
supervisord riavviava il processo in loop e l'utente vedeva solo un
traceback nei log. Ora prepare():

1. guarda se l'aggiornamento cambierà qualcosa (db_backup.pending_changes)
   e in quel caso fa il backup (db_backup.take_backup). Se il backup non si
   può fare (spazio, errore di I/O, copia che non passa il controllo) non si
   aggiorna niente.
   NAZGARR_SKIP_MIGRATION_BACKUP=1 lo salta, con un avviso;
2. scrive migration-status.json "in_progress" (su disco, prima di toccare
   il database) e aggiorna (migrations.upgrade);
3. se 1 o 2 falliscono scrive migration-status.json con l'errore e un ERROR
   nel log (cosa è successo, dov'è il backup, come ripristinarlo; il
   traceback solo nel log) e restituisce lo stato: l'app resta su in
   modalità di ripristino (nazgarr/web/recovery.py), senza scheduler, worker
   né route che toccano il DB;
4. se va tutto bene toglie migration-status.json.

Lo stesso aggiornamento ritentato non rifà il backup pre-migration. Lo si
riconosce da migration-status.json (in_progress: il processo è morto a metà,
un OOM, il SIGKILL dopo il timeout di docker stop, la corrente; o
migration_failed) e dalla versione del database, ancora quella da cui
partiva il tentativo (user_version sale solo alla fine). Il database è
quello lasciato a metà: una sua copia col nome del backup buono lo
scalzerebbe dagli ultimi KEEP, e la pagina indicherebbe di ripristinare dati
a metà. Il backup da ripristinare resta quello del primo tentativo. Se il
database è cambiato dal tentativo prima (l'impronta: dimensione, mtime,
inode, -wal; per esempio ripristinato a mano e usato per giorni con la
versione di prima) se ne fa anche una copia pre-retry, che non prende mai il
suo posto. `nazgarr db restore` toglie migration-status.json: dopo, il primo
avvio è un aggiornamento nuovo, con il suo backup."""

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
IN_PROGRESS = "in_progress"  # scritto prima di aggiornare: se resta, il processo è morto a metà
MIGRATION_FAILED = "migration_failed"
BACKUP_FAILED = "backup_failed"
UNREADABLE = "database_unreadable"  # il motivo di un backup fallito perché il DB non si legge
_ATTEMPTS = (IN_PROGRESS, MIGRATION_FAILED)
_MAX_ERROR = 300


@dataclass
class Outcome:
    engine: Engine | None = None
    status: dict | None = None  # con un valore: modalità di ripristino
    backup: Path | None = None  # il backup di prima di questo aggiornamento (del primo tentativo), se c'è
    retry: Path | None = None  # la copia pre-retry, se il database era cambiato dal tentativo prima
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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write_status(data_dir: str, status: dict) -> None:
    """Scritto accanto, su disco (fsync) e rinominato: mai un file a metà,
    e un in_progress c'è ancora dopo un'interruzione di corrente. 0600 come
    il resto della cartella dei dati."""
    target = status_path(data_dir)
    partial = target.with_name(target.name + ".partial")
    try:
        partial.unlink(missing_ok=True)
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(partial, target)
        db_backup.fsync_dir(target.parent)
    except OSError as exc:  # lo stato c'è comunque nel log e nella pagina
        logger.warning("%s not written: %s", target, exc)


def _clear_status(data_dir: str) -> None:
    path = status_path(data_dir)
    if not path.exists():
        return
    try:
        path.unlink()
        logger.info("Database updated: the earlier attempt recorded in %s is resolved, file removed", path)
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


def _existing(path: object) -> Path | None:
    return Path(path) if isinstance(path, str) and Path(path).is_file() else None


def _attempt(previous: dict | None) -> dict | None:
    """Il tentativo di aggiornamento che migration-status.json ricorda:
    interrotto (in_progress), fallito, o ricordato da un backup_failed
    venuto dopo (interrupted_update: un database tenuto da un altro
    processo, che non si legge, una copia pre-retry non riuscita)."""
    if previous and (previous.get("status") in _ATTEMPTS or previous.get("interrupted_update")):
        return previous
    return None


def _same_update(previous: dict | None, pending: db_backup.PendingChanges) -> dict | None:
    """Il tentativo di questo stesso aggiornamento, se il database è ancora
    alla versione da cui quel tentativo partiva. Qualunque sia l'impronta
    del file: un processo ucciso a metà non ha potuto scriverla, e `nazgarr
    reset-password` o un PRAGMA optimize la cambiano senza che il database
    torni quello di prima."""
    attempt = _attempt(previous)
    if attempt is None or pending.unreadable or attempt.get("from_version") != pending.version:
        return None
    return attempt


def _restore_hint(status: dict) -> str:
    backup, reason = status.get("backup"), status.get("reason")
    if status["status"] == BACKUP_FAILED and reason == UNREADABLE and not backup:
        return ("The database cannot be read (it may be damaged) and was not touched. Restore a backup of it: "
                "`nazgarr db backups` lists the ones taken before earlier updates, `nazgarr db restore <file>` puts "
                "one back (also while this page is up).")
    if status["status"] == BACKUP_FAILED and reason != UNREADABLE:
        return (f"The database was NOT updated and is unchanged. Free some space in {status['backups_dir']} "
                f"(or fix the error above) and restart Nazgarr. To update without a backup (not recommended): "
                f"{db_backup.SKIP_ENV}=1.")
    if not backup:
        text = ("No backup was taken before this update. Restore your own backup of the database if you have one, "
                f"or report the issue with this log: {PROJECT_URL}/issues.")
    else:
        text = (f"Backup taken before the update: {backup} (database version {status['from_version']}). To go back: "
                f"stop Nazgarr, replace {status['database']} with that backup and delete {DB_FILENAME}-wal, "
                f"{DB_FILENAME}-shm and {STATUS_FILENAME} next to it (or run `nazgarr db restore "
                f"{Path(backup).name}`, also while this page is up), then start the version you were using before, "
                f"or report the issue with this log: {PROJECT_URL}/issues.")
    retry = status.get("retry_backup")
    if retry:
        text += (f" The database had changed since the first attempt of this update ({status.get('started_at')}), "
                 f"so it was also copied before trying again: {retry}. Restore that one instead only if Nazgarr was "
                 "used after the first attempt, for example with the previous version.")
    return text


def _fail(settings: Settings, status: dict, exc: BaseException | None) -> dict:
    status = {
        "app_version": __version__,
        "failed_at": _now(),
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


def _backup_failed(settings: Settings, exc: db_backup.BackupError, pending: db_backup.PendingChanges,
                   previous: dict | None) -> Outcome:
    """Niente copia, niente aggiornamento. Se il database è quello lasciato
    da un tentativo precedente (o non si sa, perché non si legge), il nuovo
    stato si porta dietro quel tentativo: il prossimo avvio lo riconosce
    ancora, e il backup da indicare resta il suo."""
    # Un DB che SQLite non legge non si copia: il motivo vero è quello, e la
    # cosa da fare è ripristinare, non liberare spazio.
    reason = UNREADABLE if pending.unreadable and exc.reason == "io_error" else exc.reason
    attempt = _attempt(previous)
    if attempt is not None and not pending.unreadable \
            and attempt.get("from_version") != pending.version:
        attempt = None  # un altro database (un altro backup ripristinato): un aggiornamento nuovo
    status = {
        "status": BACKUP_FAILED, "from_version": pending.version, "to_version": migrations.LATEST, "step": None,
        "step_name": "backup", "reason": reason, "error": redact(exc.detail)[:_MAX_ERROR], "backup": None,
    }
    if attempt is not None:
        backup, retry = _existing(attempt.get("backup")), _existing(attempt.get("retry_backup"))
        status |= {
            "interrupted_update": True, "from_version": attempt.get("from_version"),
            "started_at": attempt.get("started_at"), "backup": str(backup) if backup else None,
            "retry_backup": str(retry) if retry else None, "db_fingerprint": attempt.get("db_fingerprint"),
        }
    return Outcome(from_version=status["from_version"] or 0, status=_fail(settings, status, exc))


def prepare(settings: Settings) -> Outcome:
    """Backup e aggiornamento, prima di qualunque altra cosa che usa il DB."""
    db.migrate_legacy_db_filename(settings.data_dir)
    db_path = settings.db_path
    previous = read_status(settings.data_dir)
    current = fingerprint(db_path)  # prima di aprirlo
    pending = db_backup.pending_changes(db_path)
    start, latest = pending.version, migrations.LATEST
    backup = retry = None
    started_at = _now()
    if pending.needs_backup:
        if pending.unreadable:
            logger.warning("Database not readable before the update: %s", pending.unreadable)
        folder = db_backup.backups_dir(settings.data_dir)
        keep = db_backup.keep_count()
        same = _same_update(previous, pending)
        if same is not None:
            backup = _existing(same.get("backup"))
            started_at = str(same.get("started_at") or started_at)
            previous_retry = retry = _existing(same.get("retry_backup"))
            logger.warning("The database update from version %d to %d started on %s did not finish: trying again. "
                           "Backup taken before it: %s", start, latest, started_at, backup or "none")
            # Una copia di adesso solo se il database è cambiato dal tentativo
            # prima, o se non ce n'è nessuna: mai col nome pre-migration.
            if same.get("db_fingerprint") != current or (backup is None and previous_retry is None):
                if db_backup.skip_requested():
                    logger.warning("%s is set: trying the update again WITHOUT copying the database first",
                                   db_backup.SKIP_ENV)
                else:
                    try:
                        retry = db_backup.take_backup(db_path, folder, start, latest, __version__,
                                                      kind=db_backup.PRE_RETRY)
                    except db_backup.BackupError as exc:
                        if backup is None:  # nessuna copia: niente aggiornamento
                            return _backup_failed(settings, exc, pending, previous)
                        logger.warning("Copy before trying the update again not made (%s): the backup taken before "
                                       "the update, %s, is still the one to restore", exc, backup)
                    else:
                        logger.info("The database changed since the last attempt: copied to %s before trying again "
                                    "(the backup taken before the update stays %s)", retry, backup or "none")
                        protected = (previous_retry,) if previous_retry else ()
                        for old in db_backup.prune(folder, keep, protected=protected, kind=db_backup.PRE_RETRY,
                                                   newest=retry):
                            logger.info("Old database copy removed: %s", old)
        elif db_backup.skip_requested():
            logger.warning("%s is set: updating the database from version %d to %d WITHOUT a backup",
                           db_backup.SKIP_ENV, start, latest)
        else:
            try:
                backup = db_backup.take_backup(db_path, folder, start, latest, __version__)
            except db_backup.BackupError as exc:
                return _backup_failed(settings, exc, pending, previous)
            logger.info("Backup before the database update: %s", backup)
            # Il backup appena fatto resta sempre, e anche quello che indicava
            # un fallimento precedente.
            kept = (Path(previous["backup"]),) if previous and isinstance(previous.get("backup"), str) else ()
            for old in db_backup.prune(folder, keep, protected=kept, newest=backup):
                logger.info("Old database backup removed: %s", old)
        # Su disco prima di toccare il database: un processo ucciso a metà lo
        # ritrova al prossimo avvio, con il backup del primo tentativo.
        _write_status(settings.data_dir, {
            "status": IN_PROGRESS, "app_version": __version__, "started_at": started_at, "attempt_at": _now(),
            "database": db_path, "backups_dir": str(folder), "from_version": start, "to_version": latest,
            "backup": str(backup) if backup else None, "retry_backup": str(retry) if retry else None,
            "db_fingerprint": fingerprint(db_path),
        })
    engine = db.make_engine(db_path)
    try:
        migrations.upgrade(engine)
    except migrations.MigrationFailed as exc:
        # Nessuna connessione resta aperta: il ripristino (anche `nazgarr db
        # restore`) può sostituire il file, e l'impronta è quella finale.
        engine.dispose()
        cause = exc.__cause__ or exc
        return Outcome(from_version=start, backup=backup, retry=retry, status=_fail(settings, {
            "status": MIGRATION_FAILED, "started_at": started_at,
            "from_version": exc.start if exc.start is not None else start, "to_version": latest,
            "step": exc.step, "step_name": exc.name, "error": short_error(cause),
            "backup": str(backup) if backup else None, "retry_backup": str(retry) if retry else None,
            "db_fingerprint": fingerprint(db_path),
        }, cause))
    _clear_status(settings.data_dir)
    return Outcome(engine=engine, backup=backup, retry=retry, from_version=start)


def record_backup(session: Session, outcome: Outcome) -> None:
    """Dopo un aggiornamento riuscito: il backup di prima (del primo
    tentativo, mai una copia pre-retry), per Impostazioni › Applicazione."""
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
