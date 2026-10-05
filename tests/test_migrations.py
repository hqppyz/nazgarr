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
