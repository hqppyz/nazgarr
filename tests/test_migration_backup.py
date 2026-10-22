"""Il backup prima dell'aggiornamento del database e la modalità di
ripristino (nazgarr/core/db_backup.py, nazgarr/core/db_startup.py,
nazgarr/web/recovery.py; richiesta dell'utente 2026-10-22)."""

import base64
import json
import logging
import os
import sqlite3
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from nazgarr.core import crypto, db, db_backup, db_startup, instance_lock, migrations
from nazgarr.core.config import Settings


def _database(path: Path, version: int | None = None) -> Path:
    """Un DB vero all'ultima versione, poi riportato a version (un passo
    numerato in sospeso)."""
    engine = db.make_engine(str(path))
    migrations.upgrade(engine)
    if version is not None:
        with engine.begin() as conn:
            conn.execute(text(f"PRAGMA user_version = {int(version)}"))
    engine.dispose()
    return path


def _user_version(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _failing_last_step(monkeypatch, message: str = "disco pieno") -> None:
    def boom(_engine):
        raise RuntimeError(message)

    last = migrations.MIGRATIONS[-1]
    steps = (*migrations.MIGRATIONS[:-1], migrations.Migration(last.version, last.name, boom, last.before_schema))
    monkeypatch.setattr(migrations, "MIGRATIONS", steps)


# --- cosa cambierebbe -----------------------------------------------------------


def test_nothing_to_back_up_for_a_new_an_up_to_date_or_a_newer_database(tmp_path):
    assert not db_backup.pending_changes(str(tmp_path / "none.db")).needs_backup
    (tmp_path / "empty.db").write_bytes(b"")
    assert not db_backup.pending_changes(str(tmp_path / "empty.db")).needs_backup
    sqlite3.connect(tmp_path / "no-tables.db").close()
    assert not db_backup.pending_changes(str(tmp_path / "no-tables.db")).needs_backup

    current = _database(tmp_path / "current.db")
    pending = db_backup.pending_changes(str(current))
    assert pending.has_tables and not pending.needs_backup
    assert (pending.missing_tables, pending.missing_columns, pending.missing_indexes) == ((), (), ())

    newer = _database(tmp_path / "newer.db", version=migrations.LATEST + 1)  # un downgrade
    assert not db_backup.pending_changes(str(newer)).needs_backup


def test_a_pending_step_a_missing_column_table_or_index_need_a_backup(tmp_path):
    step = _database(tmp_path / "step.db", version=migrations.LATEST - 1)
    assert db_backup.pending_changes(str(step)).needs_backup

    column = _database(tmp_path / "column.db")
    with sqlite3.connect(column) as conn:
        conn.execute("ALTER TABLE tracker DROP COLUMN rate_limit_per_min")
    pending = db_backup.pending_changes(str(column))
    assert pending.needs_backup and pending.missing_columns == ("tracker.rate_limit_per_min",)

    table = _database(tmp_path / "table.db")
    with sqlite3.connect(table) as conn:
        conn.execute("DROP TABLE event_delivery")
    pending = db_backup.pending_changes(str(table))
    assert pending.needs_backup and "event_delivery" in pending.missing_tables

    index = _database(tmp_path / "index.db")
    with sqlite3.connect(index) as conn:
        name = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%' "
                            "ORDER BY name LIMIT 1").fetchone()[0]
        conn.execute(f'DROP INDEX "{name}"')
    pending = db_backup.pending_changes(str(index))
    assert pending.needs_backup and pending.missing_indexes == (name,)


def test_after_an_upgrade_from_0_9_0_nothing_is_left_pending(tmp_path):
    """Altrimenti ogni avvio rifarebbe un backup."""
    from tests.test_migrations import _v0_9_0_database

    engine = _v0_9_0_database(tmp_path)
    path = engine.url.database
    assert db_backup.pending_changes(path).needs_backup
    migrations.upgrade(engine)
    assert not db_backup.pending_changes(path).needs_backup


# --- il backup --------------------------------------------------------------------


def test_the_backup_has_what_is_still_in_the_wal_passes_its_check_and_is_private(tmp_path):
    path = _database(tmp_path / "nazgarr.db", version=migrations.LATEST - 1)
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")  # le righe restano solo nel -wal
    writer.execute("INSERT INTO disk (label, root_path) VALUES ('only-in-the-wal', '/data/x')")
    writer.commit()
    holder = sqlite3.connect(path)  # una connessione aperta: niente checkpoint alla chiusura
    holder.execute("SELECT 1").fetchall()
    try:
        assert os.path.getsize(f"{path}-wal") > 0
        when = datetime(2026, 10, 22, 10, 15, tzinfo=UTC)
        backup = db_backup.take_backup(str(path), tmp_path / "backups", migrations.LATEST - 1, migrations.LATEST,
                                       "1.2.3+local", now=when)
    finally:
        writer.close()
        holder.close()

    assert backup.name == (f"pre-migration-v{migrations.LATEST - 1}-to-v{migrations.LATEST}-1.2.3_local-"
                           "20261022T101500Z.db")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "backups").stat().st_mode) == 0o700
    assert sorted(p.name for p in (tmp_path / "backups").iterdir()) == [backup.name]  # niente -wal, niente .partial
    assert backup.read_bytes()[18:20] == b"\x01\x01"  # un file solo, non in WAL
    copy = sqlite3.connect(f"{backup.as_uri()}?mode=ro", uri=True)
    try:
        assert copy.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert copy.execute("SELECT label FROM disk").fetchall() == [("only-in-the-wal",)]
    finally:
        copy.close()
    assert db_backup.verify(backup) == migrations.LATEST - 1
    parsed = db_backup.parse_name(backup)
    assert (parsed.from_version, parsed.to_version, parsed.created_at) == (migrations.LATEST - 1,
                                                                          migrations.LATEST, when)


def test_two_backups_in_the_same_second_do_not_collide(tmp_path):
    path = _database(tmp_path / "nazgarr.db")
    when = datetime(2026, 10, 22, 10, 15, tzinfo=UTC)
    first = db_backup.take_backup(str(path), tmp_path / "b", migrations.LATEST, migrations.LATEST, "1.0", now=when)
    second = db_backup.take_backup(str(path), tmp_path / "b", migrations.LATEST, migrations.LATEST, "1.0", now=when)
    assert first != second and first.exists() and second.exists()


def test_a_copy_left_half_done_by_a_power_cut_is_cleaned_but_not_one_in_progress(tmp_path):
    path = _database(tmp_path / "nazgarr.db")
    folder = tmp_path / "backups"
    folder.mkdir()
    old = folder / (db_backup.backup_name(1, 2, "1.0", datetime(2026, 10, 1, tzinfo=UTC)) + ".partial")
    recent = folder / (db_backup.backup_name(1, 2, "1.0", datetime(2026, 10, 2, tzinfo=UTC)) + ".partial")
    mine = folder / "pre-migration-mine.db.partial"
    for partial in (old, recent, mine):
        partial.write_bytes(b"half")
    two_hours_ago = datetime.now(UTC).timestamp() - 7200
    os.utime(old, (two_hours_ago, two_hours_ago))
    os.utime(mine, (two_hours_ago, two_hours_ago))

    db_backup.take_backup(str(path), folder, migrations.LATEST, migrations.LATEST, "1.0")

    assert not old.exists() and recent.exists() and mine.exists()


def test_no_space_means_no_backup_and_a_reason(tmp_path, monkeypatch):
    path = _database(tmp_path / "nazgarr.db")
    monkeypatch.setattr(db_backup, "_free_bytes", lambda folder: 1024)
    with pytest.raises(db_backup.BackupError) as failed:
        db_backup.take_backup(str(path), tmp_path / "backups", 1, 2, "1.0")
    assert failed.value.reason == "no_space"
    assert list((tmp_path / "backups").iterdir()) == []


def test_a_copy_that_fails_its_check_is_removed(tmp_path, monkeypatch):
    path = _database(tmp_path / "nazgarr.db")

    def broken(_path):
        raise db_backup.BackupError("verification_failed", "quick_check: page 3 is never used")

    monkeypatch.setattr(db_backup, "verify", broken)
    with pytest.raises(db_backup.BackupError) as failed:
        db_backup.take_backup(str(path), tmp_path / "backups", migrations.LATEST, migrations.LATEST, "1.0")
    assert failed.value.reason == "verification_failed"
    assert list((tmp_path / "backups").iterdir()) == []


def test_verify_refuses_what_is_not_a_good_database(tmp_path):
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"not a database at all" * 100)
    with pytest.raises(db_backup.BackupError, match="verification_failed"):
        db_backup.verify(garbage)
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    with pytest.raises(db_backup.BackupError, match="no tables"):
        db_backup.verify(empty)


def test_retention_always_keeps_the_backup_just_taken_and_anything_written_after_it(tmp_path):
    """Un orologio che era avanti (un NAS o un Raspberry senza RTC, prima
    della sincronizzazione NTP) dà ai backup vecchi un'ora nel nome più
    avanti di quello appena fatto."""
    folder = tmp_path / "backups"
    folder.mkdir()
    future = datetime.now(UTC) + timedelta(days=30)
    ahead = [folder / db_backup.backup_name(4, 5, "0.9.0", future + timedelta(days=d)) for d in range(2)]
    old = folder / db_backup.backup_name(3, 4, "0.8.0", datetime(2026, 1, 1, tzinfo=UTC))
    for path in (*ahead, old):
        path.write_bytes(b"x")
    later = future.timestamp()
    for path in ahead:
        os.utime(path, (later, later))
    os.utime(old, (1, 1))
    new = folder / db_backup.backup_name(5, 6, "0.9.1", datetime.now(UTC))
    new.write_bytes(b"x")
    retry = folder / db_backup.backup_name(5, 6, "0.9.1", datetime.now(UTC), kind=db_backup.PRE_RETRY)
    retry.write_bytes(b"x")

    removed = db_backup.prune(folder, 1, newest=new)

    assert removed == [old]  # il più vecchio sì, quelli "dal futuro" no, quello nuovo mai
    assert new.exists() and all(path.exists() for path in ahead)
    assert retry.exists()  # un altro tipo: la sua retention è un'altra
    assert [b.kind for b in db_backup.list_backups(folder, db_backup.PRE_RETRY)] == [db_backup.PRE_RETRY]


def test_retention_keeps_the_newest_and_never_touches_other_files(tmp_path, monkeypatch):
    folder = tmp_path / "backups"
    folder.mkdir()
    start = datetime(2026, 10, 1, tzinfo=UTC)
    names = [db_backup.backup_name(5, 6, "0.9.1", start + timedelta(days=d)) for d in range(5)]
    for name in names:
        (folder / name).write_bytes(b"x")
    others = ["notes.txt", "pre-migration-mine.db", "nazgarr.db", names[0] + ".partial"]
    for name in others:
        (folder / name).write_bytes(b"keep me")

    monkeypatch.setenv(db_backup.KEEP_ENV, "3")
    removed = db_backup.prune(folder, db_backup.keep_count(), protected=(folder / names[0],))

    assert sorted(p.name for p in removed) == [names[1]]
    assert sorted(p.name for p in folder.iterdir()) == sorted([names[0], *names[2:], *others])
    assert [b.name for b in db_backup.list_backups(folder)] == [names[4], names[3], names[2], names[0]]


def test_the_number_of_backups_to_keep(monkeypatch):
    monkeypatch.delenv(db_backup.KEEP_ENV, raising=False)
    assert db_backup.keep_count() == 3
    for raw, expected in (("5", 5), ("0", 1), ("-2", 1), ("many", 3)):
        monkeypatch.setenv(db_backup.KEEP_ENV, raw)
        assert db_backup.keep_count() == expected


# --- all'avvio (senza l'app) --------------------------------------------------------


def _settings(tmp_path) -> Settings:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return Settings(data_dir=str(data))


@pytest.fixture
def secret_key(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    crypto._fernet.cache_clear()
    yield
    crypto._fernet.cache_clear()


def test_prepare_backs_up_only_when_something_changes(tmp_path, secret_key, caplog):
    settings = _settings(tmp_path)
    folder = db_backup.backups_dir(settings.data_dir)

    fresh = db_startup.prepare(settings)  # installazione nuova
    assert not fresh.failed and fresh.backup is None and not folder.exists()
    fresh.engine.dispose()
    again = db_startup.prepare(settings)  # niente da cambiare
    assert again.backup is None and not folder.exists()
    again.engine.dispose()

    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(f"PRAGMA user_version = {migrations.LATEST - 1}")
    with caplog.at_level(logging.INFO, logger="nazgarr.core.db_startup"):
        updated = db_startup.prepare(settings)
    updated.engine.dispose()
    assert updated.backup is not None and updated.backup.parent == folder
    assert updated.from_version == migrations.LATEST - 1
    assert f"Backup before the database update: {updated.backup}" in caplog.text
    assert _user_version(Path(settings.db_path)) == migrations.LATEST
    assert _user_version(updated.backup) == migrations.LATEST - 1


def test_no_space_for_the_backup_leaves_the_database_alone(tmp_path, secret_key, monkeypatch, caplog):
    settings = _settings(tmp_path)
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    monkeypatch.setattr(db_backup, "_free_bytes", lambda folder: 0)
    ran = []
    monkeypatch.setattr(migrations, "upgrade", lambda engine: ran.append(engine))

    with caplog.at_level(logging.ERROR, logger="nazgarr.core.db_startup"):
        outcome = db_startup.prepare(settings)

    assert outcome.failed and outcome.engine is None and ran == []
    assert _user_version(Path(settings.db_path)) == migrations.LATEST - 1
    status = json.loads(db_startup.status_path(settings.data_dir).read_text())
    assert status["status"] == "backup_failed" and status["reason"] == "no_space"
    assert status["backup"] is None and status["from_version"] == migrations.LATEST - 1
    assert "NAZGARR_SKIP_MIGRATION_BACKUP=1" in caplog.text


def test_skipping_the_backup_on_request(tmp_path, secret_key, monkeypatch, caplog):
    settings = _settings(tmp_path)
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    monkeypatch.setenv(db_backup.SKIP_ENV, "1")
    with caplog.at_level(logging.WARNING, logger="nazgarr.core.db_startup"):
        outcome = db_startup.prepare(settings)
    outcome.engine.dispose()
    assert not outcome.failed and outcome.backup is None
    assert "WITHOUT a backup" in caplog.text
    assert not db_backup.backups_dir(settings.data_dir).exists()


def test_a_failed_step_writes_the_status_and_a_restart_keeps_the_first_backup(tmp_path, secret_key, monkeypatch,
                                                                                caplog):
    settings = _settings(tmp_path)
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    original = migrations.MIGRATIONS
    _failing_last_step(monkeypatch, "boom https://t.example/announce/abcdefghijklmnopqrstuvwxyz")

    with caplog.at_level(logging.ERROR, logger="nazgarr.core.db_startup"):
        first = db_startup.prepare(settings)

    assert first.failed and first.engine is None
    status = json.loads(db_startup.status_path(settings.data_dir).read_text())
    assert stat.S_IMODE(db_startup.status_path(settings.data_dir).stat().st_mode) == 0o600
    assert status["status"] == "migration_failed"
    assert (status["from_version"], status["to_version"]) == (migrations.LATEST - 1, migrations.LATEST)
    assert (status["step"], status["step_name"]) == (migrations.LATEST, migrations.MIGRATIONS[-1].name)
    assert status["error"] == "RuntimeError: boom https://t.example/announce/<redacted>"
    assert status["backup"] == str(first.backup) and Path(status["backup"]).is_file()
    assert datetime.fromisoformat(status["failed_at"]).tzinfo is not None
    assert "Traceback" in caplog.text and f"nazgarr db restore {first.backup.name}" in caplog.text
    assert _user_version(Path(settings.db_path)) == migrations.LATEST - 1  # la versione non sale

    # Riavvio senza toccare niente: stesso backup, nessuna copia del DB a metà.
    second = db_startup.prepare(settings)
    assert second.failed and second.backup == first.backup
    assert [b.path for b in db_backup.list_backups(db_backup.backups_dir(settings.data_dir))] == [first.backup]

    # Arriva la versione corretta: aggiorna, toglie lo stato, il backup resta quello.
    monkeypatch.setattr(migrations, "MIGRATIONS", original)
    fixed = db_startup.prepare(settings)
    fixed.engine.dispose()
    assert not fixed.failed and fixed.backup == first.backup
    assert not db_startup.status_path(settings.data_dir).exists()
    assert _user_version(Path(settings.db_path)) == migrations.LATEST


def test_a_database_changed_after_the_failure_keeps_the_first_backup_and_gets_a_retry_copy(
        tmp_path, secret_key, monkeypatch):
    """Il database cambiato dopo il tentativo fallito (scritto a metà da un
    passo, `nazgarr reset-password`, o ripristinato a mano e usato con la
    versione di prima): è ancora lo stesso aggiornamento, il backup da
    ripristinare resta quello di prima del primo tentativo. La copia di
    adesso si chiama pre-retry e non lo scalza mai, nemmeno con KEEP=1."""
    settings = _settings(tmp_path)
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    _failing_last_step(monkeypatch)
    first = db_startup.prepare(settings)
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("INSERT INTO disk (label, root_path) VALUES ('new', '/data/new')")
    monkeypatch.setenv(db_backup.KEEP_ENV, "1")

    second = db_startup.prepare(settings)

    assert second.failed and second.backup == first.backup and first.backup.is_file()
    folder = db_backup.backups_dir(settings.data_dir)
    assert [b.path for b in db_backup.list_backups(folder, db_backup.PRE_MIGRATION)] == [first.backup]
    assert second.retry is not None and second.retry.name.startswith("pre-retry-v")
    status = db_startup.read_status(settings.data_dir)
    assert (status["backup"], status["retry_backup"]) == (str(first.backup), str(second.retry))
    copy = sqlite3.connect(second.retry)
    try:
        assert copy.execute("SELECT label FROM disk").fetchall() == [("new",)]
    finally:
        copy.close()

    # Un altro riavvio, senza cambiare niente: nessuna copia nuova, e lo
    # stato indica ancora la copia pre-retry di prima.
    third = db_startup.prepare(settings)
    assert third.backup == first.backup and third.retry == second.retry
    assert len(db_backup.list_backups(folder)) == 2
    assert db_startup.read_status(settings.data_dir)["retry_backup"] == str(second.retry)


_KILLED_IN_A_STEP = """
import os, sys
from sqlalchemy import text
from nazgarr.core import db_startup, migrations
from nazgarr.core.config import Settings

def step(engine):
    with engine.begin() as conn:  # la prima metà del passo, già scritta
        conn.execute(text("INSERT INTO disk (label, root_path) "
                          "VALUES ('half-' || abs(random()), '/half/' || abs(random()))"))
    os._exit(137)  # un OOM, il SIGKILL dopo il timeout di docker stop: niente except, niente finally

last = migrations.MIGRATIONS[-1]
migrations.MIGRATIONS = (*migrations.MIGRATIONS[:-1],
                         migrations.Migration(last.version, last.name, step, last.before_schema))
db_startup.prepare(Settings(data_dir=sys.argv[1]))
"""


def test_a_process_killed_in_the_middle_of_a_step_keeps_the_original_backup(tmp_path, secret_key, monkeypatch):
    """Revisione del 2026-10-22: senza lo stato in_progress, ogni riavvio
    dopo un kill copiava il database a metà come pre-migration-v<da>-...
    e dopo KEEP riavvii il backup buono era sparito."""
    settings = _settings(tmp_path)
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    folder = db_backup.backups_dir(settings.data_dir)
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), db_backup.KEEP_ENV: "1"}
    original = None
    for attempt in range(3):
        run = subprocess.run([sys.executable, "-c", _KILLED_IN_A_STEP, settings.data_dir], env=env,
                             capture_output=True, text=True, timeout=120, check=False)
        assert run.returncode == 137, run.stderr[-2000:]
        status = db_startup.read_status(settings.data_dir)
        assert status["status"] == "in_progress" and status["from_version"] == migrations.LATEST - 1
        if original is None:
            original = Path(status["backup"])
        assert status["backup"] == str(original), attempt  # sempre quello del primo tentativo
        assert [b.path for b in db_backup.list_backups(folder, db_backup.PRE_MIGRATION)] == [original]
    copy = sqlite3.connect(original)
    try:
        assert copy.execute("SELECT count(*) FROM disk WHERE label LIKE 'half-%'").fetchone() == (0,)
    finally:
        copy.close()
    # Le copie di prima di ogni nuovo tentativo hanno un altro nome e la
    # loro retention: KEEP più quella che lo stato indica.
    retries = db_backup.list_backups(folder, db_backup.PRE_RETRY)
    assert 1 <= len(retries) <= 2 and str(retries[0].path) == status["retry_backup"]

    # Arriva la versione che non si interrompe: il backup registrato è
    # quello di prima del primo tentativo, e lo stato si toglie.
    fixed = db_startup.prepare(settings)
    fixed.engine.dispose()
    assert not fixed.failed and fixed.backup == original
    assert not db_startup.status_path(settings.data_dir).exists()


def test_a_backup_failure_after_an_interrupted_update_still_remembers_it(tmp_path, secret_key, monkeypatch):
    """Un database che dopo il kill non si legge più: il motivo è quello, e
    il backup da ripristinare resta quello di prima dell'aggiornamento,
    anche al riavvio dopo."""
    settings = _settings(tmp_path)
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    _failing_last_step(monkeypatch)
    first = db_startup.prepare(settings)
    Path(settings.db_path).write_bytes(os.urandom(20_000))
    for name in ("-wal", "-shm"):
        Path(settings.db_path + name).unlink(missing_ok=True)

    for _ in range(2):
        outcome = db_startup.prepare(settings)
        status = db_startup.read_status(settings.data_dir)
        assert outcome.failed and (status["status"], status["reason"]) == ("backup_failed", "database_unreadable")
        assert status["interrupted_update"] is True and status["backup"] == str(first.backup)
        assert status["from_version"] == migrations.LATEST - 1

    from nazgarr.web.recovery import render_page

    page = render_page(status, "en")
    assert first.backup.name in page and "cannot be read" in page
    assert len(db_backup.list_backups(db_backup.backups_dir(settings.data_dir))) == 1


def test_a_missing_retry_copy_without_any_backup_means_no_update(tmp_path, secret_key, monkeypatch):
    """Il backup del primo tentativo non c'è più (cancellato a mano): la
    copia pre-retry è l'unica, e se non si può fare non si aggiorna, ma lo
    stato ricorda ancora l'aggiornamento interrotto."""
    settings = _settings(tmp_path)
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    _failing_last_step(monkeypatch)
    first = db_startup.prepare(settings)
    first.backup.unlink()
    monkeypatch.setattr(db_backup, "_free_bytes", lambda folder: 0)
    ran = []
    monkeypatch.setattr(migrations, "upgrade", lambda engine: ran.append(engine))

    second = db_startup.prepare(settings)

    status = db_startup.read_status(settings.data_dir)
    assert second.failed and ran == []
    assert (status["status"], status["reason"], status["interrupted_update"]) == ("backup_failed", "no_space", True)
    assert not list(db_backup.backups_dir(settings.data_dir).iterdir())


def test_the_new_backup_survives_older_backups_dated_in_the_future(tmp_path, secret_key, monkeypatch, caplog):
    """Revisione del 2026-10-22: con KEEP=1 e un backup che l'orologio
    sbagliato ha datato più avanti, prepare() cancellava quello appena fatto
    e aggiornava senza backup."""
    settings = _settings(tmp_path)
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    folder = db_backup.backups_dir(settings.data_dir)
    folder.mkdir()
    future = datetime.now(UTC) + timedelta(days=30)
    ahead = folder / db_backup.backup_name(migrations.LATEST - 2, migrations.LATEST - 1, "0.9.0", future)
    _database(ahead)
    os.utime(ahead, (future.timestamp(), future.timestamp()))
    monkeypatch.setenv(db_backup.KEEP_ENV, "1")

    with caplog.at_level(logging.INFO, logger="nazgarr.core.db_startup"):
        outcome = db_startup.prepare(settings)
    outcome.engine.dispose()

    assert not outcome.failed and outcome.backup.is_file() and ahead.exists()
    assert f"Backup before the database update: {outcome.backup}" in caplog.text
    assert _user_version(Path(settings.db_path)) == migrations.LATEST
    assert _user_version(outcome.backup) == migrations.LATEST - 1


def test_a_database_held_by_another_process_is_locked_not_damaged(tmp_path, secret_key, monkeypatch):
    """Prima backup() di sqlite3 riprovava SQLITE_BUSY all'infinito e l'avvio
    restava bloccato per sempre; e un database solo tenuto da un altro
    processo era presentato come rovinato, da ripristinare."""
    from nazgarr.web.recovery import render_page

    settings = _settings(tmp_path)
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    monkeypatch.setattr(db_backup, "BUSY_TIMEOUT", 0.2)
    other = sqlite3.connect(settings.db_path, isolation_level=None)
    try:
        other.execute("PRAGMA locking_mode=EXCLUSIVE")
        other.execute("BEGIN EXCLUSIVE")
        other.execute("INSERT INTO disk (label, root_path) VALUES ('held', '/held')")
        other.execute("COMMIT")  # in modalità EXCLUSIVE il lock resta

        assert db_backup.pending_changes(settings.db_path).locked
        with pytest.raises(db_backup.BackupError) as failed:
            db_backup.take_backup(settings.db_path, tmp_path / "copies", 1, 2, "1.0")
        assert failed.value.reason == "database_locked"
        assert list((tmp_path / "copies").iterdir()) == []

        outcome = db_startup.prepare(settings)
    finally:
        other.close()

    assert outcome.failed and (outcome.status["status"], outcome.status["reason"]) == (
        "backup_failed", "database_locked")
    page = render_page(outcome.status, "en")
    assert "holds a lock" in page and "damaged" not in page and "restore" not in page.lower()
    assert _user_version(Path(settings.db_path)) == migrations.LATEST - 1
    assert not db_backup.backups_dir(settings.data_dir).exists()


@pytest.mark.parametrize("key", [None, "not-a-fernet-key"])
def test_a_missing_or_bad_secret_key_is_a_configuration_error_not_a_failed_update(tmp_path, monkeypatch, key):
    """Con APP_SECRET_KEY che manca, encrypt_plaintext_secrets falliva dentro
    l'aggiornamento e la pagina consigliava di ripristinare un backup, cioè
    di buttare via dati: la cosa da fare è impostare la chiave."""
    settings = _settings(tmp_path)
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    crypto._fernet.cache_clear()
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    if key is None:
        monkeypatch.delenv("APP_SECRET_KEY")
    else:
        monkeypatch.setenv("APP_SECRET_KEY", key)
    crypto._fernet.cache_clear()
    try:
        with pytest.raises(crypto.SecretKeyMissingError, match="APP_SECRET_KEY"):
            db_startup.prepare(settings)
    finally:
        crypto._fernet.cache_clear()
    assert _user_version(Path(settings.db_path)) == migrations.LATEST - 1
    assert not db_backup.backups_dir(settings.data_dir).exists()
    assert not db_startup.status_path(settings.data_dir).exists()


def test_the_last_backup_is_recorded_for_the_settings_page(tmp_path, secret_key):
    settings = _settings(tmp_path)
    _database(Path(settings.db_path), version=migrations.LATEST - 1)
    outcome = db_startup.prepare(settings)
    session = db.make_session_factory(outcome.engine)()
    try:
        db_startup.record_backup(session, outcome)
        recorded = db_startup.last_backup(session)
    finally:
        session.close()
        outcome.engine.dispose()
    assert recorded["path"] == str(outcome.backup)
    assert (recorded["from_version"], recorded["to_version"]) == (migrations.LATEST - 1, migrations.LATEST)
    assert datetime.fromisoformat(recorded["created_at"]).tzinfo is not None


def test_the_error_shown_has_no_query_and_no_parameters():
    from sqlalchemy.exc import IntegrityError

    exc = IntegrityError("INSERT INTO tracker VALUES (?)", ("secret-value",),
                         sqlite3.IntegrityError("UNIQUE constraint failed: tracker.label"))
    assert db_startup.short_error(exc) == "IntegrityError: UNIQUE constraint failed: tracker.label"
    assert db_startup.short_error(ValueError("x" * 1000)).startswith("ValueError: xxx")
    assert len(db_startup.short_error(ValueError("x" * 1000))) == 300


# --- l'app in modalità di ripristino -------------------------------------------------


@pytest.fixture
def app_env(tmp_path, monkeypatch, _quiet_background, secret_key):
    """Un config.yaml con un DB che ha un passo in sospeso; scheduler e
    worker contati, per vedere che non partono."""
    from nazgarr import main, scheduler

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(f"data_dir: {data_dir}\n")
    monkeypatch.setenv("CONFIG_PATH", str(config))
    _database(data_dir / "nazgarr.db", version=migrations.LATEST - 1)
    started = []
    build = scheduler.build_scheduler
    monkeypatch.setattr(scheduler, "build_scheduler", lambda *a, **k: started.append("scheduler") or build(*a, **k))
    worker = main.UploadWorker

    class CountedWorker(worker):
        def __init__(self, *args, **kwargs):
            started.append("worker")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(main, "UploadWorker", CountedWorker)
    return data_dir, started


def test_a_failed_update_keeps_the_app_up_in_recovery_mode(app_env, monkeypatch):
    from nazgarr.main import app

    data_dir, started = app_env
    _failing_last_step(monkeypatch, "secret detail token=abc123")

    with TestClient(app) as client:
        status = json.loads((data_dir / "migration-status.json").read_text())
        backup_name = Path(status["backup"]).name
        assert started == []  # niente scheduler, niente worker

        health = client.get("/api/health")
        assert health.status_code == 503 and health.json()["status"] == "database_update_failed"

        expected = {"code": "database_update_failed", "params": {
            "step": migrations.LATEST, "step_name": migrations.MIGRATIONS[-1].name, "backup": backup_name}}
        for method, path in (("get", "/api/disks"), ("post", "/api/auth/setup"), ("get", "/api/system/info"),
                             ("get", "/api/nothing-here")):
            response = getattr(client, method)(path)
            assert response.status_code == 503, path
            assert response.json()["detail"] == expected

        for path in ("/", "/library", "/assets/app.js", "/openapi.json"):
            page = client.get(path)
            assert page.status_code == 503, path
            assert page.headers["content-type"].startswith("text/html")
            assert page.headers["cache-control"] == "no-store"
            assert page.headers["content-security-policy"]  # gli header di sicurezza valgono anche qui
            assert backup_name in page.text and f"step {migrations.LATEST}" in page.text
            assert "RuntimeError" in page.text
            assert "secret detail" not in page.text and "abc123" not in page.text and "Traceback" not in page.text
            assert "<script" not in page.text

        italian = client.get("/", headers={"Accept-Language": "it-IT,it;q=0.9,en;q=0.8"})
        assert '<html lang="it">' in italian.text and "passo" in italian.text
        english = client.get("/", headers={"Accept-Language": "de-DE,en;q=0.5,it;q=0.3"})
        assert '<html lang="en">' in english.text

        # Il DB è libero: `nazgarr db restore` può lavorare anche adesso.
        lock = instance_lock.acquire(data_dir)
        assert lock is not None
        lock.release()
    assert app.state.recovery is None


def test_a_failed_backup_keeps_the_app_up_and_explains_why(app_env, monkeypatch):
    from nazgarr.main import app

    data_dir, started = app_env
    monkeypatch.setattr(db_backup, "_free_bytes", lambda folder: 0)

    with TestClient(app) as client:
        page = client.get("/", headers={"Accept-Language": "en"})
        assert page.status_code == 503 and "not enough free space" in page.text
        assert "NAZGARR_SKIP_MIGRATION_BACKUP=1" in page.text
        assert client.get("/api/health").status_code == 503
        assert started == []
    assert _user_version(data_dir / "nazgarr.db") == migrations.LATEST - 1


def test_after_a_successful_update_the_status_is_cleared_and_the_backup_shown(app_env, monkeypatch):
    from nazgarr.main import app

    data_dir, started = app_env
    _failing_last_step(monkeypatch)
    with TestClient(app):
        pass
    failed_backup = json.loads((data_dir / "migration-status.json").read_text())["backup"]
    monkeypatch.setattr(migrations, "MIGRATIONS", (
        *migrations.MIGRATIONS[:-1], migrations.Migration(migrations.LATEST, "ok", lambda engine: None, False)))

    with TestClient(app) as client:
        assert not (data_dir / "migration-status.json").exists()
        assert started == ["scheduler", "worker"]
        token = client.post("/api/auth/setup", json={
            "username": "admin", "password": "supersecret1", "setup_code": app.state.setup_code,
        }).json()["access_token"]
        info = client.get("/api/system/info", headers={"Authorization": f"Bearer {token}"}).json()
        assert client.get("/api/health").status_code == 200

    assert info["backups_dir"] == str(data_dir / "backups") and info["backups_keep"] == 3
    backup = info["migration_backup"]
    assert backup["path"] == failed_backup and backup["file"] == Path(failed_backup).name
    assert (backup["from_version"], backup["to_version"], backup["exists"]) == (
        migrations.LATEST - 1, migrations.LATEST, True)


def test_the_backup_can_be_restored_while_the_recovery_page_is_up(app_env, monkeypatch, capsys):
    """Il caso del container: `docker exec ... nazgarr db restore` con il
    server acceso in modalità di ripristino, che ha lasciato il DB."""
    from nazgarr import cli
    from nazgarr.main import app

    data_dir, _started = app_env
    _failing_last_step(monkeypatch)
    with TestClient(app) as client:
        backup = Path(json.loads((data_dir / "migration-status.json").read_text())["backup"])
        assert cli.main(["db", "restore", backup.name, "--config", os.environ["CONFIG_PATH"], "--yes"]) == 0
        assert client.get("/").status_code == 503  # resta la pagina fino al riavvio
    assert "back to version" in capsys.readouterr().out
    assert (data_dir / "nazgarr.db.before-restore").is_file()
    assert _user_version(data_dir / "nazgarr.db") == migrations.LATEST - 1


def test_a_database_that_cannot_be_read_says_so_and_points_to_the_backups(app_env):
    from nazgarr.main import app

    data_dir, started = app_env
    (data_dir / "nazgarr.db").write_bytes(os.urandom(20_000))

    with TestClient(app) as client:
        page = client.get("/", headers={"Accept-Language": "en"})
    assert page.status_code == 503 and "cannot be read" in page.text and "nazgarr db restore" in page.text
    assert "NAZGARR_SKIP_MIGRATION_BACKUP" not in page.text
    status = json.loads((data_dir / "migration-status.json").read_text())
    assert (status["status"], status["reason"]) == ("backup_failed", "database_unreadable")
    assert started == []
