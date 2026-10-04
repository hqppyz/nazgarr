"""Segreti cifrati a riposo (nazgarr/core/db.py encrypt_plaintext_secrets, nazgarr/core/settings_repo.py)."""

from datetime import UTC, datetime

from sqlalchemy import text

from nazgarr.core import db as db_module
from nazgarr.core import settings_repo, startup_checks
from nazgarr.core.models import ClientTorrent, TorrentClient, Tracker


def _raw(session, sql, **params):
    return session.execute(text(sql), params).scalar()


def test_secret_settings_are_stored_encrypted_and_read_back_in_clear(db_session):
    settings_repo.set_setting(db_session, "tmdb_api_key", "tmdb-123")
    settings_repo.set_setting(db_session, "rematch_interval_days", "7")

    stored = _raw(db_session, "SELECT value FROM app_settings WHERE key = 'tmdb_api_key'")
    assert stored.startswith("enc:") and "tmdb-123" not in stored
    assert settings_repo.get_setting(db_session, "tmdb_api_key") == "tmdb-123"
    assert _raw(db_session, "SELECT value FROM app_settings WHERE key = 'rematch_interval_days'") == "7"


def test_an_existing_instance_is_migrated_and_still_starts(db_session):
    engine = db_session.get_bind()
    startup_checks.verify_secret_key(db_session)  # il canary di un'istanza già in uso
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    client = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q")
    db_session.add_all([tracker, client])
    db_session.commit()
    # Come li avevano lasciati le versioni di prima: in chiaro.
    db_session.execute(text("UPDATE tracker SET announce_url = 'https://t.example/announce/PASSKEY123'"))
    db_session.execute(text("INSERT INTO app_settings (key, value) VALUES ('image_host_ptpimg_api_key', 'pk-1')"))
    db_session.add(ClientTorrent(torrent_client_id=client.id, info_hash="h", name="n", save_path="/s",
                                 state="uploading", tracker_url="https://t.example:443/announce/PASSKEY123",
                                 last_polled_at=datetime.now(UTC)))
    db_session.commit()

    assert db_module.encrypt_plaintext_secrets(engine) == 3
    assert db_module.encrypt_plaintext_secrets(engine) == 0  # idempotente
    db_session.expire_all()

    assert "PASSKEY123" not in _raw(db_session, "SELECT announce_url FROM tracker")
    assert db_session.get(Tracker, tracker.id).announce_url == "https://t.example/announce/PASSKEY123"
    assert _raw(db_session, "SELECT tracker_url FROM client_torrent") == "https://t.example:443"
    assert settings_repo.get_setting(db_session, "image_host_ptpimg_api_key") == "pk-1"
    startup_checks.verify_secret_key(db_session)  # il canary è intatto: l'app riparte
