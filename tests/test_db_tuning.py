"""Le impostazioni di SQLite su ogni connessione (nazgarr/core/db.py,
_configure_sqlite; audit 2026-10-18)."""

import sqlite3
import time

import pytest
from sqlalchemy import text

from nazgarr.core import db, migrations


def _pragmas(engine) -> dict[str, object]:
    with engine.connect() as conn:
        return {name: conn.execute(text(f"PRAGMA {name}")).scalar()
                for name in ("foreign_keys", "journal_mode", "synchronous", "cache_size", "busy_timeout")}


def test_every_connection_is_configured(tmp_path):
    """synchronous resta FULL (2): con NORMAL un'interruzione di corrente può
    perdere il commit di 'uploading' fatto prima di chiamare il tracker, e il
    worker rifarebbe l'upload (revisione dell'audit 2026-10-18)."""
    engine = db.make_engine(str(tmp_path / "db.db"))
    assert _pragmas(engine) == {
        "foreign_keys": 1, "journal_mode": "wal", "synchronous": 2, "cache_size": -16384, "busy_timeout": 30000,
    }


def _database_with_media_files(tmp_path):
    engine = db.make_engine(str(tmp_path / "db.db"))
    migrations.upgrade(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO run_log (id, run_type, started_at) VALUES (1, 'manual', '2026-10-18')"))
        conn.execute(text("INSERT INTO disk (id, label, root_path) VALUES (1, 'd', '/d')"))
        for i in range(200):
            conn.execute(text(
                "INSERT INTO media_file (disk_id, relative_path, size_bytes, st_dev, inode, last_scan_id, "
                "last_seen_at) VALUES (1, :p, 1, 1, :i, 1, '2026-10-18')"), {"p": f"m{i}", "i": i})
    engine.dispose()
    return engine


def _media_file_rows_in_statistics(engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT stat FROM sqlite_stat1 WHERE tbl = 'media_file' AND idx = 'idx_media_file_media_item_id'"
        )).scalar()


@pytest.mark.skipif(sqlite3.sqlite_version_info < (3, 46, 0),
                    reason="PRAGMA optimize guarda tutte le tabelle solo da SQLite 3.46")
def test_the_planner_gets_statistics_once_there_is_data(tmp_path):
    engine = _database_with_media_files(tmp_path)  # poi dispose: come una connessione che il pool riapre

    with engine.connect() as conn:
        tables = conn.execute(text("SELECT DISTINCT tbl FROM sqlite_stat1")).scalars().all()
    assert "media_file" in tables


@pytest.mark.parametrize("checks_all_tables", [db.OPTIMIZE_CHECKS_ALL_TABLES, False],
                         ids=["this-sqlite", "before-3.46"])
def test_after_a_restart_the_planner_has_statistics(tmp_path, monkeypatch, checks_all_tables):
    """Con qualsiasi SQLite: prima della 3.46 la PRAGMA optimize all'apertura
    non vede nessuna tabella, e le statistiche le fa l'ANALYZE dell'avvio."""
    monkeypatch.setattr(db, "OPTIMIZE_CHECKS_ALL_TABLES", checks_all_tables)
    engine = _database_with_media_files(tmp_path)

    migrations.upgrade(engine)  # il riavvio

    assert (_media_file_rows_in_statistics(engine) or "").startswith("200 ")


def test_a_new_connection_does_not_wait_for_another_writer(tmp_path):
    """Le statistiche sono un di più: con il lock in scrittura di un altro,
    aprire una connessione non aspetta i 30 secondi di busy_timeout."""
    path = tmp_path / "db.db"
    engine = db.make_engine(str(path))
    migrations.upgrade(engine)
    engine.dispose()
    writer = sqlite3.connect(path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        start = time.monotonic()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM disk")).scalar() == 0
        assert time.monotonic() - start < 5
    finally:
        writer.rollback()
        writer.close()
