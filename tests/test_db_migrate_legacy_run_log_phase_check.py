"""Copre un terzo bug nella stessa famiglia, scoperto verificando dal vivo
il fix precedente (tests/test_db_migrate_legacy_media_path_id.py): un DB
creato prima del commit 1149b94 ha ancora il vecchio CHECK più stretto su
run_log.current_phase (solo 'scanning'/'matching'/'executing') — con
media_file/seed_file finalmente funzionanti, la primissima transizione di
fase successiva a "scanning" (nazgarr/pipeline.py::_set_phase, phase
"resolving") fa fallire di nuovo la run, stavolta con
"CHECK constraint failed: current_phase IN (...)". Mai riprodottosi
sull'istanza reale dell'utente solo perché lo scan falliva prima ancora
di arrivarci."""

from sqlalchemy import text

from nazgarr import db as db_module

LEGACY_RUN_LOG_SCHEMA = """
CREATE TABLE disk (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE
);

CREATE TABLE run_log (
    id                  INTEGER PRIMARY KEY,
    run_type            TEXT NOT NULL CHECK (run_type IN ('scheduled','manual','bulk_import')),
    started_at          TIMESTAMP NOT NULL,
    finished_at         TIMESTAMP,
    current_phase       TEXT CHECK (current_phase IN ('scanning','matching','executing')),
    phase_total         INTEGER,
    phase_done          INTEGER,
    items_total         INTEGER,
    items_scanned       INTEGER DEFAULT 0,
    matches_found        INTEGER DEFAULT 0,
    auto_executed         INTEGER DEFAULT 0,
    pending_review       INTEGER DEFAULT 0,
    orphan_torrent_count  INTEGER DEFAULT 0,
    ignored_count         INTEGER DEFAULT 0,
    health_snapshot       REAL,
    errors                INTEGER DEFAULT 0,
    last_error            TEXT
);

CREATE TABLE media_file (
    id                      INTEGER PRIMARY KEY,
    disk_id                 INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
    relative_path           TEXT NOT NULL,
    size_bytes              INTEGER NOT NULL,
    st_dev                  INTEGER NOT NULL,
    inode                   INTEGER NOT NULL,
    last_scan_id            INTEGER NOT NULL REFERENCES run_log(id),
    last_seen_at            TIMESTAMP NOT NULL,
    UNIQUE(disk_id, relative_path)
);
"""


def _seed_legacy_run_log_db(engine):
    raw_conn = engine.raw_connection()
    try:
        raw_conn.executescript(LEGACY_RUN_LOG_SCHEMA)
        raw_conn.executescript("""
            INSERT INTO disk (id, label, root_path) VALUES (1, 'Data', '/data');
            INSERT INTO run_log (id, run_type, started_at, current_phase, items_scanned, errors)
                VALUES (1, 'manual', '2026-09-22T20:00:00', 'scanning', 3, 0);
            INSERT INTO media_file (
                id, disk_id, relative_path, size_bytes, st_dev, inode, last_scan_id, last_seen_at
            ) VALUES (
                42, 1, 'media/tv/Show/S01E01.mkv', 12345, 55, 999, 1, '2026-09-22T20:00:00'
            );
        """)
        raw_conn.commit()
    finally:
        raw_conn.close()


def test_migrate_legacy_run_log_phase_check_allows_the_new_phase_values(tmp_path):
    engine = db_module.make_engine(str(tmp_path / "legacy_run_log.db"))
    _seed_legacy_run_log_db(engine)

    db_module.migrate_legacy_run_log_phase_check(engine)

    # Lo stesso UPDATE che nazgarr/pipeline.py::_set_phase emette per ogni
    # transizione di fase reale — prima di questa migrazione avrebbe fatto
    # fallire ogni run con "CHECK constraint failed" alla primissima fase
    # successiva a "scanning".
    with engine.begin() as conn:
        for phase in ("resolving", "indexing", "matching", "executing", "reconciling"):
            conn.execute(text("UPDATE run_log SET current_phase = :p WHERE id = 1"), {"p": phase})


def test_migrate_legacy_run_log_phase_check_preserves_data_and_referencing_fk(tmp_path):
    engine = db_module.make_engine(str(tmp_path / "legacy_run_log.db"))
    _seed_legacy_run_log_db(engine)

    db_module.migrate_legacy_run_log_phase_check(engine)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT run_type, current_phase, items_scanned, errors FROM run_log WHERE id = 1")
        ).one()
        assert row == ("manual", "scanning", 3, 0)

        # La FK di media_file.last_scan_id verso run_log non deve essersi rotta.
        media_row = conn.execute(text("SELECT last_scan_id FROM media_file WHERE id = 42")).one()
        assert media_row == (1,)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO media_file (disk_id, relative_path, size_bytes, st_dev, inode, "
                "last_scan_id, last_seen_at) "
                "VALUES (1, 'media/tv/Show/S01E02.mkv', 999, 55, 1000, 1, '2026-09-22T20:00:00')"
            )
        )


def test_migrate_legacy_run_log_phase_check_is_a_noop_on_current_schema(tmp_path):
    engine = db_module.make_engine(str(tmp_path / "current.db"))
    db_module.migrate_legacy_run_log_phase_check(engine)  # DB vuoto: nessuna tabella run_log, nessun errore
    db_module.apply_schema(engine)
    db_module.migrate_schema(engine)

    db_module.migrate_legacy_run_log_phase_check(engine)  # già nella forma corrente: no-op
    with engine.connect() as conn:
        sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='run_log'")
        ).scalar()
        assert "reconciling" in sql
