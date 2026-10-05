"""Le migrazioni con una versione (nazgarr/core/migrations.py)."""

from sqlalchemy import inspect, text

from nazgarr.core import db, migrations


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
    """I passi sono idempotenti: un avvio interrotto li ripete tutti."""
    import pytest

    engine = db.make_engine(str(tmp_path / "db.db"))

    def boom(_engine):
        raise RuntimeError("disco pieno")

    steps = (*migrations.MIGRATIONS[:-1], migrations.Migration(migrations.LATEST, "x", boom, False))
    monkeypatch.setattr(migrations, "MIGRATIONS", steps)
    with pytest.raises(RuntimeError):
        migrations.upgrade(engine)
    assert migrations.current_version(engine) == 0


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
