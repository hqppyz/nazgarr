"""Copre due bug in sequenza, entrambi riportati dall'utente sulla sua
istanza Unraid reale:

1. Un DB creato prima del commit 5fd42fc ha ancora la vecchia tabella
   media_file con media_path_id NOT NULL (FK verso la media_path ormai
   rimossa dallo schema corrente) — ogni scan falliva al primo INSERT.
   db.migrate_legacy_media_path_id() ricostruisce media_file senza quella
   colonna, preservando gli id (da cui dipendono seed_file/match_review/
   seed_job/upload_job) e i dati già presenti.

2. La PRIMA versione di quella migrazione faceva
   ALTER TABLE media_file RENAME TO media_file_legacy prima di ricrearla —
   ma SQLite riscrive le REFERENCES di OGNI altra tabella verso quella
   rinominata SEMPRE, non solo con le foreign key attive (verificato con
   un test diretto, vedi il warning in cima ad nazgarr/db.py). Dopo il DROP
   finale, seed_file/match_review/seed_job/upload_job restavano agganciate
   per sempre a "media_file_legacy" — un nome ormai inesistente. Sintomo
   riportato: "no such table: media_file_legacy" su un INSERT in
   seed_file, DOPO il deploy della prima versione della migrazione.
   db.repair_dangling_media_file_legacy_fk() ripara chi ha già subito
   questo danno."""

import sqlite3

import pytest
from sqlalchemy import inspect, text

from nazgarr import db as db_module

LEGACY_SCHEMA = """
CREATE TABLE disk (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    st_dev INTEGER,
    torrents_rel_path TEXT,
    torrent_client_root_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE media_path (
    id INTEGER PRIMARY KEY,
    disk_id INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('movie','tv')),
    enabled BOOLEAN NOT NULL DEFAULT 1,
    new_torrent_rel_path TEXT,
    UNIQUE(disk_id, relative_path)
);

CREATE TABLE run_log (
    id INTEGER PRIMARY KEY,
    run_type TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL
);

CREATE TABLE media_item (
    id INTEGER PRIMARY KEY,
    content_type TEXT NOT NULL,
    tmdb_id INTEGER NOT NULL
);

CREATE TABLE tracker (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE candidate (
    id INTEGER PRIMARY KEY,
    media_item_id INTEGER NOT NULL REFERENCES media_item(id) ON DELETE CASCADE,
    tracker_id INTEGER NOT NULL REFERENCES tracker(id)
);

CREATE TABLE client_torrent (
    id INTEGER PRIMARY KEY
);

CREATE TABLE media_file (
    id INTEGER PRIMARY KEY,
    media_path_id INTEGER NOT NULL REFERENCES media_path(id) ON DELETE CASCADE,
    disk_id INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    st_dev INTEGER NOT NULL,
    inode INTEGER NOT NULL,
    nlink INTEGER,
    content_hash TEXT,
    media_item_id INTEGER REFERENCES media_item(id) ON DELETE SET NULL,
    resolver_source TEXT,
    mediainfo_unique_id TEXT,
    last_scan_id INTEGER NOT NULL REFERENCES run_log(id),
    last_seen_at TIMESTAMP NOT NULL,
    UNIQUE(disk_id, relative_path)
);

CREATE TABLE seed_file (
    id INTEGER PRIMARY KEY,
    disk_id INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    st_dev INTEGER NOT NULL,
    inode INTEGER NOT NULL,
    media_file_id INTEGER REFERENCES media_file(id) ON DELETE SET NULL,
    last_scan_id INTEGER NOT NULL REFERENCES run_log(id),
    last_seen_at TIMESTAMP NOT NULL,
    UNIQUE(disk_id, relative_path)
);

CREATE TABLE match_review (
    id              INTEGER PRIMARY KEY,
    candidate_id    INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    media_file_id   INTEGER REFERENCES media_file(id) ON DELETE CASCADE,
    seed_file_id    INTEGER REFERENCES seed_file(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending',
    decided_by      TEXT,
    decided_at      TIMESTAMP
);

CREATE TABLE seed_job (
    id                          INTEGER PRIMARY KEY,
    candidate_id                INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    source_media_file_id        INTEGER REFERENCES media_file(id),
    source_seed_file_id         INTEGER REFERENCES seed_file(id),
    result_seed_file_id         INTEGER REFERENCES seed_file(id),
    result_client_torrent_id    INTEGER REFERENCES client_torrent(id),
    info_hash                   TEXT,
    hardlink_created_at         TIMESTAMP,
    torrent_added_at            TIMESTAMP,
    recheck_status               TEXT,
    final_status                 TEXT NOT NULL DEFAULT 'in_progress',
    error_message                TEXT
);

CREATE TABLE upload_job (
    id                      INTEGER PRIMARY KEY,
    media_file_id           INTEGER REFERENCES media_file(id),
    source_path             TEXT NOT NULL,
    tracker_id              INTEGER NOT NULL REFERENCES tracker(id),
    status                  TEXT NOT NULL DEFAULT 'draft'
);
"""

_SIBLING_TABLES = ("seed_file", "match_review", "seed_job", "upload_job")


def _seed_legacy_db(engine):
    raw_conn = engine.raw_connection()
    try:
        raw_conn.executescript(LEGACY_SCHEMA)
        raw_conn.executescript("""
            INSERT INTO disk (id, label, root_path) VALUES (1, 'Data', '/data');
            INSERT INTO media_path (id, disk_id, relative_path, content_type)
                VALUES (1, 1, 'media/tv', 'tv');
            INSERT INTO run_log (id, run_type, started_at)
                VALUES (1, 'manual', '2026-09-22T20:00:00');
            INSERT INTO media_file (
                id, media_path_id, disk_id, relative_path, size_bytes, st_dev, inode,
                last_scan_id, last_seen_at
            ) VALUES (
                42, 1, 1, 'media/tv/Show/S01E01.mkv', 12345, 55, 999,
                1, '2026-09-22T20:00:00'
            );
            INSERT INTO seed_file (
                id, disk_id, relative_path, size_bytes, st_dev, inode, media_file_id,
                last_scan_id, last_seen_at
            ) VALUES (
                7, 1, 'torrents/Show/S01E01.mkv', 12345, 55, 999, 42,
                1, '2026-09-22T20:00:00'
            );
        """)
        raw_conn.commit()
    finally:
        raw_conn.close()


def _replay_old_buggy_migration(engine):
    """Riproduce ESATTAMENTE la prima versione (sbagliata) di
    migrate_legacy_media_path_id(), per costruire in un test un DB nello
    stesso stato corrotto di quello reale dell'utente dopo il primo
    deploy: media_file già corretta (senza media_path_id), ma
    seed_file/match_review/seed_job/upload_job con la FK riscritta su
    "media_file_legacy" da SQLite durante il RENAME — non va mai
    reintrodotta nel codice vero, esiste solo qui come fixture."""
    raw_conn = engine.raw_connection()
    try:
        raw_conn.executescript("""
            PRAGMA foreign_keys=OFF;
            ALTER TABLE media_file RENAME TO media_file_legacy;
            CREATE TABLE media_file (
                id                      INTEGER PRIMARY KEY,
                disk_id                 INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
                relative_path           TEXT NOT NULL,
                size_bytes              INTEGER NOT NULL,
                st_dev                  INTEGER NOT NULL,
                inode                   INTEGER NOT NULL,
                nlink                   INTEGER,
                content_hash            TEXT,
                media_item_id           INTEGER REFERENCES media_item(id) ON DELETE SET NULL,
                resolver_source         TEXT,
                mediainfo_unique_id     TEXT,
                last_scan_id            INTEGER NOT NULL REFERENCES run_log(id),
                last_seen_at            TIMESTAMP NOT NULL,
                UNIQUE(disk_id, relative_path)
            );
            INSERT INTO media_file (
                id, disk_id, relative_path, size_bytes, st_dev, inode, nlink,
                content_hash, media_item_id, resolver_source, mediainfo_unique_id,
                last_scan_id, last_seen_at
            )
            SELECT
                id, disk_id, relative_path, size_bytes, st_dev, inode, nlink,
                content_hash, media_item_id, resolver_source, mediainfo_unique_id,
                last_scan_id, last_seen_at
            FROM media_file_legacy;
            DROP TABLE media_file_legacy;
            DROP TABLE IF EXISTS media_path;
            PRAGMA foreign_keys=ON;
        """)
        raw_conn.commit()
    finally:
        raw_conn.close()


def _sibling_sql_texts(engine):
    with engine.connect() as conn:
        return {
            name: conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}
            ).scalar()
            for name in _SIBLING_TABLES
        }


def test_migrate_legacy_media_path_id_preserves_data_and_ids(tmp_path):
    engine = db_module.make_engine(str(tmp_path / "legacy.db"))
    _seed_legacy_db(engine)

    db_module.migrate_legacy_media_path_id(engine)

    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("media_file")}
    assert "media_path_id" not in columns
    assert not inspector.has_table("media_path")

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, disk_id, relative_path, size_bytes FROM media_file WHERE id = 42")
        ).one()
        assert row == (42, 1, "media/tv/Show/S01E01.mkv", 12345)

        seed_row = conn.execute(text("SELECT media_file_id FROM seed_file WHERE id = 7")).one()
        assert seed_row == (42,)


def test_migrate_legacy_media_path_id_does_not_corrupt_sibling_fk_text(tmp_path):
    """Il bug esatto della prima versione: un RENAME sulla tabella già
    referenziata fa riscrivere a SQLite le REFERENCES di ogni altra
    tabella, SEMPRE (non solo con le foreign key attive). La versione
    corretta non rinomina mai media_file — verifica qui che nessuna
    tabella "sorella" ne risenta, e che l'enforcement reale della FK
    funzioni ancora (non solo che il testo sia giusto)."""
    engine = db_module.make_engine(str(tmp_path / "legacy.db"))
    _seed_legacy_db(engine)

    db_module.migrate_legacy_media_path_id(engine)

    for name, sql in _sibling_sql_texts(engine).items():
        assert sql is not None, name
        assert "media_file_legacy" not in sql, f"{name}: {sql}"

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO seed_file "
                "(disk_id, relative_path, size_bytes, st_dev, inode, media_file_id, last_scan_id, last_seen_at) "
                "VALUES (1, 'torrents/Show/S01E02.mkv', 999, 55, 1001, 42, 1, '2026-09-22T20:00:00')"
            )
        )

    raw_conn = engine.raw_connection()
    try:
        raw_conn.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            raw_conn.execute(
                "INSERT INTO seed_file "
                "(disk_id, relative_path, size_bytes, st_dev, inode, media_file_id, last_scan_id, last_seen_at) "
                "VALUES (1, 'torrents/Show/bogus.mkv', 1, 55, 2, 999999, 1, '2026-09-22T20:00:00')"
            )
    finally:
        raw_conn.close()


def test_migrate_legacy_media_path_id_allows_insert_without_the_column(tmp_path):
    engine = db_module.make_engine(str(tmp_path / "legacy.db"))
    _seed_legacy_db(engine)
    db_module.migrate_legacy_media_path_id(engine)

    # Lo stesso INSERT che nazgarr/db_utils.py::bulk_upsert emette per uno scan
    # reale (nazgarr/scanner.py) — mai valorizza media_path_id, che prima di
    # questa migrazione avrebbe fatto fallire ogni scan con
    # "NOT NULL constraint failed: media_file.media_path_id".
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO media_file "
                "(disk_id, relative_path, size_bytes, st_dev, inode, last_scan_id, last_seen_at) "
                "VALUES (1, 'media/tv/Show/S01E02.mkv', 999, 55, 1000, 1, '2026-09-22T20:00:00')"
            )
        )


def test_migrate_legacy_media_path_id_is_a_noop_on_current_schema(tmp_path):
    engine = db_module.make_engine(str(tmp_path / "current.db"))
    db_module.migrate_legacy_media_path_id(engine)  # DB vuoto: nessuna tabella media_file, nessun errore
    db_module.apply_schema(engine)
    db_module.migrate_schema(engine)

    # Rilanciarla su uno schema già corrente non deve toccare nulla né rompersi.
    db_module.migrate_legacy_media_path_id(engine)
    inspector = inspect(engine)
    assert inspector.has_table("media_file")
    columns = {col["name"] for col in inspector.get_columns("media_file")}
    assert "media_path_id" not in columns


def test_repair_dangling_media_file_legacy_fk_fixes_already_corrupted_db(tmp_path):
    engine = db_module.make_engine(str(tmp_path / "corrupted.db"))
    _seed_legacy_db(engine)
    _replay_old_buggy_migration(engine)

    # Precondizione: la fixture riproduce davvero il danno riportato dall'utente.
    corrupted = _sibling_sql_texts(engine)
    assert any("media_file_legacy" in (sql or "") for sql in corrupted.values())

    db_module.repair_dangling_media_file_legacy_fk(engine)

    for name, sql in _sibling_sql_texts(engine).items():
        assert sql is not None, name
        assert "media_file_legacy" not in sql, f"{name}: {sql}"

    with engine.connect() as conn:
        seed_row = conn.execute(text("SELECT media_file_id FROM seed_file WHERE id = 7")).one()
        assert seed_row == (42,)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO seed_file "
                "(disk_id, relative_path, size_bytes, st_dev, inode, media_file_id, last_scan_id, last_seen_at) "
                "VALUES (1, 'torrents/Show/S01E03.mkv', 999, 55, 1002, 42, 1, '2026-09-22T20:00:00')"
            )
        )


def test_repair_dangling_media_file_legacy_fk_is_a_noop_when_nothing_broken(tmp_path):
    engine = db_module.make_engine(str(tmp_path / "clean.db"))
    _seed_legacy_db(engine)
    db_module.migrate_legacy_media_path_id(engine)  # versione corretta: non corrompe nulla

    db_module.repair_dangling_media_file_legacy_fk(engine)  # non deve rompere/toccare nulla

    with engine.connect() as conn:
        seed_row = conn.execute(text("SELECT media_file_id FROM seed_file WHERE id = 7")).one()
        assert seed_row == (42,)


def test_repair_dangling_media_file_legacy_fk_is_a_noop_on_empty_db(tmp_path):
    engine = db_module.make_engine(str(tmp_path / "empty.db"))
    db_module.repair_dangling_media_file_legacy_fk(engine)  # nessuna tabella media_file: nessun errore
