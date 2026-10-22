"""Le migrazioni con una versione (nazgarr/core/migrations.py)."""

from pathlib import Path

from sqlalchemy import inspect, text

from nazgarr.core import db, migrations

FIXTURES = Path(__file__).parent / "fixtures"

# Una riga o due in ogni tabella con una foreign key, con lo schema della
# 0.9.0 (la prima stabile con le versioni, ultima migrazione 9): solo colonne
# che c'erano già allora.
_V0_9_0_ROWS = """
INSERT INTO run_log (id, run_type, started_at) VALUES (1, 'manual', '2026-10-01 10:00:00');
INSERT INTO disk (id, label, root_path) VALUES (1, 'd1', '/data/d1'), (2, 'd2', '/data/d2');
INSERT INTO disk_folder (disk_id, kind, relative_path) VALUES (1, 'media', 'media'), (1, 'seeding', 'torrents');
INSERT INTO tracker (id, label, adapter_type, base_url, api_token)
    VALUES (1, 'T1', 'unit3d', 'https://t1.example', 'enc:x'), (2, 'T2', 'unit3d', 'https://t2.example', 'enc:y');
INSERT INTO torrent_client (id, label, adapter_type, base_url) VALUES (1, 'qb', 'qbittorrent', 'http://qb:8080');
INSERT INTO disk_torrent_client (disk_id, torrent_client_id) VALUES (1, 1);
INSERT INTO media_item (id, content_type, tmdb_id) VALUES (1, 'movie', 603);
INSERT INTO media_file (id, disk_id, relative_path, size_bytes, st_dev, inode, media_item_id, last_scan_id,
                        last_seen_at)
    VALUES (1, 1, 'media/m.mkv', 100, 1, 10, 1, 1, '2026-10-01'), (2, 2, 'media/n.mkv', 200, 2, 20, 1, 1, '2026-10-01');
INSERT INTO seed_file (id, disk_id, relative_path, size_bytes, st_dev, inode, media_file_id, last_scan_id, last_seen_at)
    VALUES (1, 1, 'torrents/m.mkv', 100, 1, 10, 1, 1, '2026-10-01'),
           (2, 1, 'torrents/o.mkv', 300, 1, 30, NULL, 1, '2026-10-01');
INSERT INTO client_torrent (id, torrent_client_id, info_hash, name, save_path, state, last_polled_at)
    VALUES (1, 1, 'aa', 'm', '/data/d1/torrents', 'uploading', '2026-10-01');
INSERT INTO client_torrent_file (id, client_torrent_id, path_in_torrent, size_bytes, seed_file_id, last_scan_id)
    VALUES (1, 1, 'm.mkv', 100, 1, 1);
INSERT INTO candidate (id, media_item_id, tracker_id, torrent_id_remote, name, size_bytes, source, direction,
                       confidence)
    VALUES (1, 1, 1, '11', 'm', 100, 'history', 'media_to_torrent', 1.0),
           (2, 1, 1, '12', 'o', 300, 'catalog_search', 'torrent_to_client', 1.0),
           (3, 1, 2, '13', 'n', 200, 'history', 'media_to_torrent', 0.5);
INSERT INTO candidate_file (id, candidate_id, torrent_path, is_video, media_file_id, seed_file_id)
    VALUES (1, 1, 'm.mkv', 1, 1, NULL), (2, 2, 'o.mkv', 1, NULL, 2), (3, 3, 'n.mkv', 1, 2, NULL);
INSERT INTO match_review (id, candidate_id, media_file_id, seed_file_id, status)
    VALUES (1, 1, 1, NULL, 'approved'), (2, 2, NULL, 2, 'approved'), (3, 3, 2, NULL, 'pending');
INSERT INTO match_attempt (id, tracker_id, media_file_id, seed_file_id, size_bytes, tmdb_id, attempted_at)
    VALUES (1, 1, 1, NULL, 100, 603, '2026-10-01'), (2, 1, NULL, 2, 300, 603, '2026-10-01'),
           (3, 2, 2, NULL, 200, 603, '2026-10-01');
INSERT INTO seed_job (id, candidate_id, source_media_file_id, source_seed_file_id, result_seed_file_id,
                      result_client_torrent_id, info_hash, final_status)
    VALUES (1, 1, 1, NULL, 1, 1, 'aa', 'seeding'), (2, 2, NULL, 2, NULL, NULL, 'bb', 'failed'),
           (3, 3, 2, NULL, NULL, NULL, 'cc', 'seeding');
INSERT INTO not_imported_torrent (id, client_torrent_id, category, replaced_by_media_file_id, total_bytes, video_bytes,
                                  file_count, run_id)
    VALUES (1, 1, 'superseded', 1, 100, 100, 1, 1);
INSERT INTO file_change (id, run_id, side, disk_id, relative_path, size_bytes, change)
    VALUES (1, 1, 'media', 1, 'media/m.mkv', 100, 'added');
INSERT INTO tracker_health_snapshot (id, run_id, scope) VALUES (1, 1, 'configured');
INSERT INTO tracker_upload_profile (tracker_id) VALUES (1);
INSERT INTO upload_job (id, disk_id, relative_path, source_path, status)
    VALUES (1, 1, 'media/m.mkv', '/data/d1/media/m.mkv', 'done'), (2, 2, 'media/n.mkv', '/data/d2/media/n.mkv', 'done');
INSERT INTO upload_target (id, job_id, tracker_id, torrent_client_id, status) VALUES (1, 1, 1, 1, 'done');
INSERT INTO upload_event (id, job_id, target_id, code) VALUES (1, 1, 1, 'uploaded');
INSERT INTO watch_entry (id, disk_id, relative_path, size_bytes, mtime, stable_since, job_id)
    VALUES (1, 1, 'watch/m', 100, 1.0, '2026-10-01', 1);
INSERT INTO event (id, name, payload_json) VALUES (1, 'run.finished', '{}');
INSERT INTO webhook (id, name, url, secret, events_json) VALUES (1, 'w', 'https://hook.example', 'enc:s', '["*"]');
INSERT INTO notification_service (id, name, adapter_type, events_json) VALUES (1, 'n', 'discord', '["*"]');
INSERT INTO event_delivery (id, event_id, webhook_id, notification_id) VALUES (1, 1, 1, NULL), (2, 1, NULL, 1);
PRAGMA user_version = 9;
"""


def _v0_9_0_database(tmp_path, extra: str = ""):
    engine = db.make_engine(str(tmp_path / "v0.9.0.db"))
    raw = engine.raw_connection()
    try:
        raw.executescript((FIXTURES / "schema_v0.9.0.sql").read_text() + _V0_9_0_ROWS + extra)
        raw.commit()
    finally:
        raw.close()
    return engine


def _tables(engine) -> list[str]:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )).scalars().all()


def _counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {t: conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in _tables(engine)}


def _structure(engine) -> dict[str, tuple]:
    """Colonne, foreign key (con l'azione ON DELETE) e indici di ogni tabella:
    quello che un aggiornamento e un'installazione nuova devono avere uguale."""
    with engine.connect() as conn:
        def rows(pragma, table):
            return conn.execute(text(f'PRAGMA {pragma}("{table}")')).all()

        return {
            t: (
                {r[1] for r in rows("table_info", t)},
                {(r[3], r[2], r[4], r[6]) for r in rows("foreign_key_list", t)},
                {r[1] for r in rows("index_list", t) if not r[1].startswith("sqlite_autoindex")},
            )
            for t in _tables(engine)
        }


def test_an_upgrade_from_0_9_0_keeps_every_row_and_ends_like_a_new_database(tmp_path):
    """Un DB creato dalla 0.9.0, con dati: l'aggiornamento non perde righe,
    non lascia riferimenti rotti e arriva alla forma di un DB nuovo (anche
    gli indici su colonne arrivate dopo, come upload_job.split_from_id, e le
    azioni ON DELETE del passo 10)."""
    old = _v0_9_0_database(tmp_path)
    before = _counts(old)

    migrations.upgrade(old)

    after = _counts(old)
    assert {t: after[t] for t in before} == before
    with old.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
    new = db.make_engine(str(tmp_path / "new.db"))
    migrations.upgrade(new)
    assert _structure(old) == _structure(new)


# Un DB fra la 0.9.0 e la 0.9.4: migrate_schema aveva aggiunto
# upload_job.split_from_id con un ALTER TABLE, senza foreign key. Un pack
# diviso (10) va in 'cancelled', i suoi episodi (11) puntano a lui.
_SPLIT_PACK_BEFORE_0_9_4 = """
ALTER TABLE upload_job ADD COLUMN "split_from_id" INTEGER;
INSERT INTO upload_job (id, disk_id, relative_path, source_path, is_dir, status)
    VALUES (10, 1, 'media/pack', '/data/d1/media/pack', 1, 'cancelled');
INSERT INTO upload_job (id, disk_id, relative_path, source_path, status, split_from_id)
    VALUES (11, 1, 'media/pack/e1.mkv', '/data/d1/media/pack/e1.mkv', 'done', 10);
"""


def _split_from(engine) -> int | None:
    with engine.connect() as conn:
        return conn.execute(text("SELECT split_from_id FROM upload_job WHERE id = 11")).scalar()


def test_a_split_pack_deleted_before_the_foreign_key_does_not_stop_the_upgrade(tmp_path):
    """Revisione dell'audit 2026-10-18: il pack cancellato lasciava ai figli
    un id che non c'è più, e la FK nuova del passo 10 li vedeva come
    riferimenti rotti: l'upgrade falliva a ogni avvio, ferma alla versione 9.
    Si azzerano, come avrebbe fatto ON DELETE SET NULL."""
    engine = _v0_9_0_database(tmp_path, _SPLIT_PACK_BEFORE_0_9_4 + "DELETE FROM upload_job WHERE id = 10;")

    migrations.upgrade(engine)

    assert migrations.current_version(engine) == migrations.LATEST
    assert _split_from(engine) is None
    assert _ids(engine, "upload_job") == [1, 2, 11]
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []


def test_a_split_pack_still_there_keeps_its_children_and_gets_the_foreign_key(tmp_path):
    engine = _v0_9_0_database(tmp_path, _SPLIT_PACK_BEFORE_0_9_4)

    migrations.upgrade(engine)

    assert _split_from(engine) == 10
    with engine.connect() as conn:
        fks = {(r[3], r[2], r[6]) for r in conn.execute(text("PRAGMA foreign_key_list(upload_job)"))}
        assert ("split_from_id", "upload_job", "SET NULL") in fks
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM upload_job WHERE id = 10"))
    assert _split_from(engine) is None


def test_a_new_foreign_key_that_cannot_be_null_stops_on_its_column(tmp_path):
    """Una FK nuova che non è SET NULL non sa cosa fare di un valore che
    punta al vuoto: il passo si ferma e dice dove, il DB resta com'era."""
    import pytest

    engine = db.make_engine(str(tmp_path / "db.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER)"))
        conn.execute(text("INSERT INTO parent (id) VALUES (1)"))
        conn.execute(text("INSERT INTO child (id, parent_id) VALUES (1, 1), (2, 7)"))
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE parent (id INTEGER PRIMARY KEY);\n"
                      "CREATE TABLE child (id INTEGER PRIMARY KEY,"
                      " parent_id INTEGER REFERENCES parent(id) ON DELETE CASCADE);\n")

    with pytest.raises(RuntimeError, match="child: 1 valori di parent_id"):
        db.rebuild_tables_from_schema(engine, ("child",), schema_path=schema)

    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_list(child)")).all() == []
        assert conn.execute(text("SELECT id, parent_id FROM child ORDER BY id")).all() == [(1, 1), (2, 7)]


def test_a_new_database_ends_at_the_latest_version_with_every_table(tmp_path):
    engine = db.make_engine(str(tmp_path / "new.db"))
    assert migrations.upgrade(engine) == 0
    assert migrations.current_version(engine) == migrations.LATEST
    assert {"media_file", "seed_file", "disk_folder", "upload_job"} <= set(inspect(engine).get_table_names())


def test_one_time_steps_run_once_and_the_schema_sync_every_time(tmp_path, monkeypatch):
    engine = db.make_engine(str(tmp_path / "db.db"))
    migrations.upgrade(engine)
    ran, synced = [], []
    steps = tuple(
        migrations.Migration(m.version, m.name, lambda e, v=m.version: ran.append(v), m.before_schema)
        for m in migrations.MIGRATIONS
    )
    monkeypatch.setattr(migrations, "MIGRATIONS", steps)
    real_schema = db.migrate_schema
    monkeypatch.setattr(db, "migrate_schema", lambda e: synced.append(1) or real_schema(e))

    assert migrations.upgrade(engine) == migrations.LATEST
    assert ran == [] and synced == [1]

    with engine.begin() as conn:  # un DB di prima delle versioni
        conn.execute(text("PRAGMA user_version = 0"))
    migrations.upgrade(engine)
    assert sorted(ran) == list(range(1, migrations.LATEST + 1))
    assert migrations.current_version(engine) == migrations.LATEST


def test_a_failed_step_does_not_move_the_version(tmp_path, monkeypatch):
    """I passi sono idempotenti: un avvio interrotto li ripete tutti. Il
    passo che fallisce dice il suo numero e il suo nome, per la modalità di
    ripristino (nazgarr/core/db_startup.py)."""
    import pytest

    engine = db.make_engine(str(tmp_path / "db.db"))

    def boom(_engine):
        raise RuntimeError("disco pieno")

    steps = (*migrations.MIGRATIONS[:-1], migrations.Migration(migrations.LATEST, "x", boom, False))
    monkeypatch.setattr(migrations, "MIGRATIONS", steps)
    with pytest.raises(migrations.MigrationFailed) as failed:
        migrations.upgrade(engine)
    assert (failed.value.step, failed.value.name, failed.value.start) == (migrations.LATEST, "x", 0)
    assert isinstance(failed.value.__cause__, RuntimeError)
    assert migrations.current_version(engine) == 0


def test_a_failure_outside_the_numbered_steps_names_its_function(tmp_path, monkeypatch):
    import pytest

    engine = db.make_engine(str(tmp_path / "db.db"))
    migrations.upgrade(engine)

    def boom(_engine):
        raise ValueError("chiave sbagliata")

    monkeypatch.setattr(db, "encrypt_plaintext_secrets", boom)
    with pytest.raises(migrations.MigrationFailed) as failed:
        migrations.upgrade(engine)
    assert (failed.value.step, failed.value.name, failed.value.start) == (
        None, "encrypt_plaintext_secrets", migrations.LATEST)


def _ids(engine, table: str) -> list[int]:
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT id FROM "{table}" ORDER BY id')).scalars().all()


def test_after_the_upgrade_a_used_tracker_and_a_used_disk_can_be_deleted(tmp_path):
    """Audit 2026-10-18: candidate.tracker_id e i file di partenza di seed_job
    non avevano un'azione alla cancellazione, e cancellare un tracker che
    aveva trovato un candidato, o un disco con un reseed, dava un 500
    (FOREIGN KEY constraint failed). Lo stesso DELETE delle API, con le
    foreign key accese come in ogni connessione dell'app."""
    engine = _v0_9_0_database(tmp_path)
    migrations.upgrade(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tracker WHERE id = 2"))  # il candidato 3, la sua review, il suo seed_job
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM disk WHERE id = 1"))  # i file 1 di media e di seed: i seed_job 1 e 2

    assert _ids(engine, "candidate") == [1, 2]
    assert _ids(engine, "seed_job") == []
    assert _ids(engine, "match_review") == []
    assert _ids(engine, "candidate_file") == [1, 2]
    assert _ids(engine, "client_torrent") == [1]  # il torrent nel client resta, la sua riga anche
    assert _ids(engine, "upload_job") == [1, 2]  # lo storico degli upload resta, senza disco
    with engine.connect() as conn:
        assert conn.execute(text("SELECT disk_id FROM upload_job WHERE id = 1")).scalar() is None
        assert conn.execute(text("SELECT media_file_id, seed_file_id FROM candidate_file")).all() == [
            (None, None), (None, None)]
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []


def test_the_foreign_key_step_runs_once_and_an_interrupted_one_runs_again(tmp_path, monkeypatch):
    """Il passo 10 rifà candidate, seed_job e upload_job in una transazione:
    interrotto a metà, il DB resta com'era e il riavvio lo ripete; dopo,
    rilanciarlo non tocca niente."""
    import sqlite3

    import pytest

    from tests.db_faults import fail_once

    engine = _v0_9_0_database(tmp_path)
    before = _counts(engine)
    with monkeypatch.context() as patch:
        fail_once(patch, engine, sqlite3.SQLITE_ALTER_TABLE, "seed_job__rebuild")
        with pytest.raises(sqlite3.DatabaseError):
            db.migrate_foreign_key_actions(engine)
    assert _counts(engine) == before
    with engine.connect() as conn:
        assert {fk[6] for fk in conn.execute(text("PRAGMA foreign_key_list(candidate)"))} == {"CASCADE", "NO ACTION"}

    assert db.migrate_foreign_key_actions(engine) == ["candidate", "seed_job", "upload_job"]
    assert db.migrate_foreign_key_actions(engine) == []
    assert _counts(engine) == before
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_the_app_starts_on_fresh_connections_after_the_upgrade(tmp_path, monkeypatch):
    """Un passo che lascia una connessione senza foreign key (come facevano i
    passi 2 e 3, audit 2026-10-18) non la passa all'app: le sessioni
    successive le hanno tutte accese."""

    def leaves_foreign_keys_off(engine):
        raw = engine.raw_connection()
        raw.cursor().execute("PRAGMA foreign_keys=OFF")
        raw.close()

    steps = (*migrations.MIGRATIONS[:-1], migrations.Migration(migrations.LATEST, "x", leaves_foreign_keys_off, False))
    monkeypatch.setattr(migrations, "MIGRATIONS", steps)
    engine = db.make_engine(str(tmp_path / "db.db"))
    migrations.upgrade(engine)

    sessions = [db.make_session_factory(engine)() for _ in range(3)]
    try:
        assert [s.execute(text("PRAGMA foreign_keys")).scalar() for s in sessions] == [1, 1, 1]
    finally:
        for s in sessions:
            s.close()


def test_notification_services_become_instances(tmp_path):
    """Migrazione 6: la configurazione per tipo (adapter_config) diventa una
    riga di notification_service e le consegne puntano all'istanza."""
    engine = db.make_engine(str(tmp_path / "db.db"))
    migrations.upgrade(engine)
    with engine.begin() as conn:  # la forma di prima
        conn.execute(text("DROP TABLE event_delivery"))
        conn.execute(text(
            "CREATE TABLE event_delivery (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, webhook_id INTEGER, "
            "notification_type TEXT, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, "
            "next_attempt_at TIMESTAMP, last_status_code INTEGER, last_error TEXT, delivered_at TIMESTAMP, "
            "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.execute(text("ALTER TABLE adapter_config ADD COLUMN events_json TEXT"))
        conn.execute(text("INSERT INTO adapter_config (kind, adapter_type, enabled, config_json, events_json) "
                          "VALUES ('notification', 'telegram', 1, 'enc:x', '[\"run.finished\"]'), "
                          "('image_host', 'ntfy_img', 1, NULL, NULL)"))
        conn.execute(text("INSERT INTO event (id, name, payload_json) VALUES (1, 'run.finished', '{}')"))
        conn.execute(text("INSERT INTO event_delivery (id, event_id, notification_type) "
                          "VALUES (1, 1, 'telegram'), (2, 1, 'gone')"))
        conn.execute(text("PRAGMA user_version = 5"))

    migrations.upgrade(engine)

    with engine.connect() as conn:
        services = conn.execute(text(
            "SELECT id, name, adapter_type, config_json, events_json FROM notification_service")).all()
        assert [tuple(s[1:]) for s in services] == [("Telegram", "telegram", "enc:x", '["run.finished"]')]
        assert conn.execute(text("SELECT id, notification_id FROM event_delivery")).all() == [(1, services[0][0])]
        assert conn.execute(text("SELECT kind FROM adapter_config")).scalars().all() == ["image_host"]
        fks = conn.execute(text("PRAGMA foreign_key_list(event_delivery)")).all()
        assert {fk[2] for fk in fks} == {"event", "webhook", "notification_service"}
    assert "notification_type" not in {c["name"] for c in inspect(engine).get_columns("event_delivery")}
