"""Il passo di migrazione che riporta entro i limiti dell'API il
rate_limit_per_min dei tracker salvati prima che l'API li avesse (audit
2026-10-18, finding 121)."""

from sqlalchemy import text

from nazgarr.api.trackers import RATE_LIMIT_MAX
from nazgarr.core import db, migrations


def _rate_limits(engine) -> dict[int, int | None]:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, rate_limit_per_min FROM tracker ORDER BY id")).all())


def test_stored_rate_limits_outside_the_api_bounds_are_normalized(tmp_path):
    engine = db.make_engine(str(tmp_path / "n.db"))
    migrations.upgrade(engine)
    values = {1: -5, 2: 0, 3: 45, 4: 100_000, 5: None, 6: 1, 7: RATE_LIMIT_MAX}
    with engine.begin() as conn:
        for tracker_id, value in values.items():
            conn.execute(text("INSERT INTO tracker (id, label, adapter_type, base_url, api_token, rate_limit_per_min) "
                              "VALUES (:id, :label, 'unit3d', 'https://t.example', 'enc:x', :rate)"),
                         {"id": tracker_id, "label": f"T{tracker_id}", "rate": value})

    assert migrations.normalize_tracker_rate_limits(engine) == {"defaulted": 2, "capped": 1}

    assert _rate_limits(engine) == {1: 30, 2: 30, 3: 45, 4: RATE_LIMIT_MAX, 5: None, 6: 1, 7: RATE_LIMIT_MAX}
    assert migrations.normalize_tracker_rate_limits(engine) == {"defaulted": 0, "capped": 0}  # idempotente


def test_the_step_runs_on_upgrade_from_the_version_before(tmp_path):
    engine = db.make_engine(str(tmp_path / "n.db"))
    migrations.upgrade(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO tracker (id, label, adapter_type, base_url, api_token, rate_limit_per_min) "
                          "VALUES (1, 'T', 'unit3d', 'https://t.example', 'enc:x', -1)"))
        step = next(m for m in migrations.MIGRATIONS if m.run is migrations.normalize_tracker_rate_limits)
        conn.execute(text(f"PRAGMA user_version = {step.version - 1}"))

    migrations.upgrade(engine)

    assert _rate_limits(engine) == {1: 30}
    assert migrations.current_version(engine) == migrations.LATEST
