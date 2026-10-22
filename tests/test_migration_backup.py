"""Il backup prima dell'aggiornamento del database (nazgarr/core/db_backup.py,
richiesta dell'utente 2026-10-22)."""

import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from nazgarr.core import db, db_backup, migrations


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
