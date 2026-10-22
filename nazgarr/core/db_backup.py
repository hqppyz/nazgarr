"""Il backup del database prima di un aggiornamento (richiesta dell'utente,
2026-10-22).

All'avvio, prima che nazgarr/core/migrations.py cambi qualcosa, se c'è
qualcosa da cambiare (pending_changes: passi numerati in sospeso, o tabelle,
colonne e indici che migrate_schema e apply_schema aggiungerebbero) il
database si copia in <data_dir>/backups:

- con l'API di backup online di SQLite, che legge anche le transazioni
  ancora nel -wal (una copia del solo file .db le perderebbe);
- in un file solo, in modalità DELETE e non WAL: si ripristina copiandolo;
- creato 0600 prima di scriverci (dentro ci sono i segreti cifrati e i dati
  personali), scritto su disco (fsync) e solo allora rinominato col nome
  finale, poi riletto e controllato (PRAGMA quick_check e la versione);
- solo se c'è spazio per il database, il suo -wal e un margine.

Il nome dice tutto quello che serve per ripristinarlo:
pre-migration-v<da>-to-v<a>-<versione di Nazgarr>-<ora UTC>.db, dove <da> è
la versione dello schema (PRAGMA user_version) del backup. Un nuovo
tentativo dello stesso aggiornamento (dopo un processo ucciso a metà o un
passo fallito) non fa mai un altro pre-migration: il database è quello
lasciato a metà, e quella copia scalzerebbe il backup buono. Se il database
è cambiato dal tentativo prima, la copia si chiama pre-retry-v<da>-...
(nazgarr/core/db_startup.py). Restano gli ultimi KEEP backup di ciascun
tipo (NAZGARR_MIGRATION_BACKUPS_KEEP, 3 di default), sempre quello appena
fatto; gli altri file della cartella non si toccano mai.

Lo usano l'avvio (nazgarr/core/db_startup.py) e il CLI locale
(`nazgarr db backups`, `nazgarr db restore`, nazgarr/cli.py)."""

import logging
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

BACKUPS_DIRNAME = "backups"
KEEP_ENV = "NAZGARR_MIGRATION_BACKUPS_KEEP"
SKIP_ENV = "NAZGARR_SKIP_MIGRATION_BACKUP"
DEFAULT_KEEP = 3
PRE_MIGRATION = "pre-migration"  # il database prima del primo tentativo di un aggiornamento
PRE_RETRY = "pre-retry"  # il database prima di un nuovo tentativo, se è cambiato da quello prima
# Oltre al database e al suo -wal: il file temporaneo del journal di SQLite
# mentre scrive la copia, e un po' di respiro per il resto del sistema.
MARGIN_BYTES = 32 * 1024 * 1024
_STAMP = "%Y%m%dT%H%M%SZ"
_NAME = re.compile(r"^(?P<kind>pre-migration|pre-retry)-v(?P<start>\d+)-to-v(?P<end>\d+)"
                   r"-(?P<version>[A-Za-z0-9._-]+)-(?P<stamp>\d{8}T\d{6}Z)\.db$")


class BackupError(Exception):
    """Il backup non si è fatto: reason è no_space, io_error o
    verification_failed (un codice per la pagina di ripristino), detail un
    testo breve per il log e per migration-status.json."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


@dataclass(frozen=True)
class PendingChanges:
    """Cosa cambierebbe l'aggiornamento: letto senza scrivere niente."""
    version: int  # PRAGMA user_version del DB
    latest: int  # migrations.LATEST
    has_tables: bool
    missing_tables: tuple[str, ...] = ()
    missing_columns: tuple[str, ...] = ()  # "tabella.colonna"
    missing_indexes: tuple[str, ...] = ()
    unreadable: str | None = None  # il DB non si legge: meglio un backup (che dirà se si può fare)

    @property
    def needs_backup(self) -> bool:
        """Un DB nuovo o vuoto non ha niente da salvare; uno più nuovo di
        questo Nazgarr (un downgrade) non riceve nessun passo."""
        if self.unreadable:
            return True
        if not self.has_tables or self.version > self.latest:
            return False
        return (self.version < self.latest or bool(self.missing_tables) or bool(self.missing_columns)
                or bool(self.missing_indexes))


@dataclass(frozen=True)
class BackupFile:
    path: Path
    from_version: int
    to_version: int
    app_version: str
    created_at: datetime
    size: int
    kind: str = PRE_MIGRATION

    @property
    def name(self) -> str:
        return self.path.name


def backups_dir(data_dir: str | os.PathLike) -> Path:
    return Path(data_dir) / BACKUPS_DIRNAME


def keep_count() -> int:
    """Quanti backup tenere: almeno 1, quello appena fatto."""
    raw = os.environ.get(KEEP_ENV, "").strip()
    if not raw:
        return DEFAULT_KEEP
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("%s=%r is not a number: keeping %d backups", KEEP_ENV, raw, DEFAULT_KEEP)
        return DEFAULT_KEEP


def skip_requested() -> bool:
    return os.environ.get(SKIP_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def backup_name(from_version: int, to_version: int, app_version: str, when: datetime,
                kind: str = PRE_MIGRATION) -> str:
    version = re.sub(r"[^A-Za-z0-9._-]+", "_", app_version).strip("._-") or "unknown"
    return f"{kind}-v{from_version}-to-v{to_version}-{version}-{when.astimezone(UTC).strftime(_STAMP)}.db"


def parse_name(path: Path) -> BackupFile | None:
    """Un file di questo modulo, coi dati del suo nome; None per ogni altro."""
    match = _NAME.match(path.name)
    if not match:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    return BackupFile(
        path=path, from_version=int(match["start"]), to_version=int(match["end"]), app_version=match["version"],
        created_at=datetime.strptime(match["stamp"], _STAMP).replace(tzinfo=UTC), size=size, kind=match["kind"],
    )


def list_backups(folder: Path, kind: str | None = None) -> list[BackupFile]:
    """I backup prima di un aggiornamento (di un tipo, o tutti), dal più
    recente."""
    if not folder.is_dir():
        return []
    found = [b for b in (parse_name(p) for p in folder.iterdir() if p.is_file())
             if b is not None and kind in (None, b.kind)]
    return sorted(found, key=lambda b: (b.created_at, b.name), reverse=True)


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def prune(folder: Path, keep: int, protected: tuple[Path, ...] = (), *, kind: str = PRE_MIGRATION,
          newest: Path | None = None) -> list[Path]:
    """Tiene i keep più recenti di un tipo, più quelli in protected (il
    backup che la pagina di ripristino indica ancora) e newest, quello
    appena fatto. L'ordine è l'ora nel nome, e un orologio che era avanti (un
    NAS o un Raspberry senza RTC, prima della sincronizzazione NTP) può
    mettere dei backup vecchi davanti a quello appena fatto: quello resta
    comunque, e non si cancella niente scritto dopo di lui (mtime). Solo
    file con il nome di questo modulo: nient'altro della cartella si tocca."""
    keep_paths = {p.resolve() for p in (*protected, *((newest,) if newest else ()))}
    limit = _mtime(newest) if newest else None
    removed = []
    for backup in list_backups(folder, kind)[keep:]:
        if backup.path.resolve() in keep_paths:
            continue
        written = _mtime(backup.path)
        if limit is not None and written is not None and written >= limit:
            continue
        try:
            backup.path.unlink()
            removed.append(backup.path)
        except OSError as exc:
            logger.warning("Old database backup not removed: %s (%s)", backup.path, exc)
    return removed


# --- cosa cambierebbe -------------------------------------------------------


@cache
def _schema_objects() -> frozenset[tuple[str, str]]:
    """Tabelle e indici di docs/schema.sql, creati in memoria."""
    from nazgarr.core.db import SCHEMA_PATH

    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        return frozenset(conn.execute(
            "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall())
    finally:
        conn.close()


def pending_changes(db_path: str) -> PendingChanges:
    """Cosa farebbe migrations.upgrade su questo file, solo leggendo: la
    versione (passi numerati), le tabelle e gli indici di schema.sql che
    mancano (apply_schema), le colonne dei modelli che mancano
    (migrate_schema). Una connessione sqlite3 sua, non quella dell'app:
    _configure_sqlite all'apertura può scrivere (PRAGMA optimize)."""
    from nazgarr.core.migrations import LATEST
    from nazgarr.core.models import Base

    if not os.path.isfile(db_path) or os.path.getsize(db_path) == 0:
        return PendingChanges(version=0, latest=LATEST, has_tables=False)
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0] or 0
            objects = set(conn.execute(
                "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall())
            tables = {name for kind, name in objects if kind == "table"}
            if not tables:
                return PendingChanges(version=version, latest=LATEST, has_tables=False)
            expected = _schema_objects()
            missing_tables = sorted(name for kind, name in expected if kind == "table" and name not in tables)
            missing_indexes = sorted(name for kind, name in expected
                                     if kind == "index" and (kind, name) not in objects)
            missing_columns = []
            for table in Base.metadata.sorted_tables:
                if table.name not in tables:
                    continue
                existing = {row[1] for row in conn.execute(f'PRAGMA table_info("{table.name}")')}
                missing_columns += [f"{table.name}.{c.name}" for c in table.columns if c.name not in existing]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return PendingChanges(version=0, latest=LATEST, has_tables=True, unreadable=f"{type(exc).__name__}: {exc}")
    return PendingChanges(version=version, latest=LATEST, has_tables=True, missing_tables=tuple(missing_tables),
                          missing_columns=tuple(missing_columns), missing_indexes=tuple(missing_indexes))


# --- il backup ----------------------------------------------------------------


def _free_bytes(folder: Path) -> int:
    return shutil.disk_usage(folder).free


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def required_space(db_path: str) -> int:
    used = _size(db_path) + _size(db_path + "-wal")
    return used + used // 10 + MARGIN_BYTES


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_dir(folder: Path) -> None:
    """Il rename resta anche dopo un'interruzione di corrente. Non su Windows,
    dove una cartella non si apre."""
    if os.name == "nt":
        return
    _fsync(folder)


def _new_private_file(path: Path) -> None:
    """Vuoto e 0600 prima che ci finisca dentro qualcosa: mai un momento in
    cui il backup è leggibile da altri utenti, qualunque sia la umask."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)


def copy_database(source: str, target: Path) -> None:
    """Una copia coerente di source in target (che non deve esistere): l'API
    di backup online, poi la copia passa da WAL a DELETE, così è un file solo.
    Scritta su disco prima di tornare."""
    _new_private_file(target)
    # mode=rw: un database che non c'è è un errore, non un file vuoto nuovo.
    src = sqlite3.connect(f"{Path(source).resolve().as_uri()}?mode=rw", uri=True, timeout=30)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            # L'API copia anche l'intestazione: la copia nascerebbe in WAL, e
            # aprendola comparirebbero -wal e -shm accanto.
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()
    os.chmod(target, 0o600)
    _fsync(target)


def verify(path: Path) -> int:
    """Controlla un backup (solo lettura): si apre, PRAGMA quick_check dice
    ok, ha delle tabelle. Restituisce la sua versione dello schema;
    BackupError(verification_failed) se non va."""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
        try:
            check = [row[0] for row in conn.execute("PRAGMA quick_check").fetchall()]
            tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
            version = conn.execute("PRAGMA user_version").fetchone()[0] or 0
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise BackupError("verification_failed", f"{type(exc).__name__}: {exc}") from exc
    if check != ["ok"]:
        raise BackupError("verification_failed", "quick_check: " + "; ".join(check[:3]))
    if not tables:
        raise BackupError("verification_failed", "no tables")
    return version


def _remove_stale_partials(folder: Path, now: datetime) -> None:
    """Una copia rimasta a metà da un'interruzione di corrente: nostra (il
    nome di questo modulo più .partial), vecchia di più di un'ora (mai quella
    di un altro avvio in corso), e non serve a niente. Il resto della
    cartella non si tocca."""
    for path in folder.glob("pre-*.db.partial"):
        try:
            if _NAME.match(path.name.removesuffix(".partial")) and \
                    now.timestamp() - path.stat().st_mtime > 3600:
                path.unlink()
        except OSError:
            pass


def take_backup(db_path: str, folder: Path, from_version: int, to_version: int, app_version: str,
                now: datetime | None = None, kind: str = PRE_MIGRATION) -> Path:
    """Il backup prima dell'aggiornamento, controllato. BackupError se non si
    può fare: allora non si aggiorna niente (nazgarr/core/db_startup.py)."""
    when = now or datetime.now(UTC)
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        needed, free = required_space(db_path), _free_bytes(folder)
    except OSError as exc:
        raise BackupError("io_error", f"{type(exc).__name__}: {exc}") from exc
    if free < needed:
        raise BackupError("no_space", f"{free} bytes free in {folder}, {needed} needed")
    _remove_stale_partials(folder, when)
    # Due backup nello stesso secondo (un riavvio veloce): il secondo dopo.
    target = folder / backup_name(from_version, to_version, app_version, when, kind)
    for _ in range(60):
        if not target.exists():
            break
        when += timedelta(seconds=1)
        target = folder / backup_name(from_version, to_version, app_version, when, kind)
    partial = target.with_name(target.name + ".partial")
    try:
        copy_database(db_path, partial)
        os.replace(partial, target)
        fsync_dir(folder)
    except (OSError, sqlite3.Error) as exc:
        partial.unlink(missing_ok=True)
        raise BackupError("io_error", f"{type(exc).__name__}: {exc}") from exc
    try:
        version = verify(target)
    except BackupError:
        target.unlink(missing_ok=True)
        raise
    if version != from_version:
        target.unlink(missing_ok=True)
        raise BackupError("verification_failed", f"the copy has schema version {version}, not {from_version}")
    return target


# --- il ripristino (CLI) --------------------------------------------------------


def sidecars(db_path: str) -> tuple[Path, Path]:
    return Path(db_path + "-wal"), Path(db_path + "-shm")


def keep_current(db_path: str, now: datetime | None = None) -> Path:
    """Prima di un ripristino: il database di adesso come <nome>.before-restore
    (con l'ora, se ce n'è già uno), byte per byte, col suo -wal accanto
    (<nome>.before-restore-wal: SQLite li riapre insieme). Non con l'API di
    backup: chi ripristina tiene il lucchetto, nessuno scrive, e un file che
    SQLite non legge (un aggiornamento finito male) va tenuto com'è; una
    prima prova con SQLite su un file così può già togliergli il -wal."""
    target = Path(db_path + ".before-restore")
    if target.exists() or Path(f"{target}-wal").exists():
        stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime(_STAMP)
        target = Path(f"{db_path}.before-restore-{stamp}")
    wal, copied_wal = sidecars(db_path)[0], Path(f"{target}-wal")
    try:
        _new_private_file(target)
        shutil.copyfile(db_path, target)
        _fsync(target)
        if wal.exists() and wal.stat().st_size:
            _new_private_file(copied_wal)
            shutil.copyfile(wal, copied_wal)
            _fsync(copied_wal)
    except OSError:
        target.unlink(missing_ok=True)
        copied_wal.unlink(missing_ok=True)
        raise
    return target


def restore(backup: Path, db_path: str) -> None:
    """Il backup al posto del database: copiato accanto, scritto su disco,
    poi -wal e -shm via (un -wal rimasto verrebbe riapplicato sopra il
    backup) e infine il rename, che non lascia mai un database a metà."""
    target = Path(db_path)
    staging = target.with_name(target.name + ".restoring")
    staging.unlink(missing_ok=True)
    try:
        _new_private_file(staging)
        shutil.copyfile(backup, staging)
        os.chmod(staging, 0o600)
        _fsync(staging)
    except OSError:
        staging.unlink(missing_ok=True)  # il database non è ancora stato toccato
        raise
    for sidecar in sidecars(db_path):
        sidecar.unlink(missing_ok=True)
    os.replace(staging, target)
    fsync_dir(target.parent)
