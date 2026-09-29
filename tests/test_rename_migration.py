"""Rename del progetto Gauntletarr -> Nazgarr: i dati esistenti restano."""

from app import crypto, db, startup_checks
from app.models import AppSetting


def test_the_old_database_file_is_renamed_with_its_sqlite_sidecars(tmp_path):
    (tmp_path / "gauntletarr.db").write_bytes(b"db")
    (tmp_path / "gauntletarr.db-wal").write_bytes(b"wal")

    assert db.migrate_legacy_db_filename(str(tmp_path)) == str(tmp_path / "nazgarr.db")

    assert (tmp_path / "nazgarr.db").read_bytes() == b"db"
    assert (tmp_path / "nazgarr.db-wal").read_bytes() == b"wal"
    assert not (tmp_path / "gauntletarr.db").exists()


def test_with_both_files_the_new_one_wins_and_nothing_is_touched(tmp_path):
    (tmp_path / "gauntletarr.db").write_bytes(b"old")
    (tmp_path / "nazgarr.db").write_bytes(b"new")

    assert db.migrate_legacy_db_filename(str(tmp_path)) is None
    assert (tmp_path / "nazgarr.db").read_bytes() == b"new"
    assert (tmp_path / "gauntletarr.db").read_bytes() == b"old"


def test_a_fresh_install_has_nothing_to_migrate(tmp_path):
    assert db.migrate_legacy_db_filename(str(tmp_path)) is None


def test_the_old_secret_key_check_is_accepted_and_rewritten(db_session):
    db_session.add(AppSetting(key="app_secret_key_canary", value=crypto.encrypt("gauntletarr-secret-key-check")))
    db_session.commit()

    startup_checks.verify_secret_key(db_session)  # nessun errore: stessa chiave, testo vecchio

    row = db_session.get(AppSetting, "app_secret_key_canary")
    assert crypto.decrypt(row.value) == "nazgarr-secret-key-check"
