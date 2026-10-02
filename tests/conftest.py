import base64
import os

import pytest
from fastapi.testclient import TestClient

from nazgarr import crypto as crypto_module
from nazgarr import db as db_module


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    # Stesso motivo del fixture `client` sotto: crypto._fernet() è cachata per
    # processo, va pulita qui altrimenti un test precedente nella stessa
    # sessione pytest "vince" la chiave per chi crea un Tracker/TorrentClient
    # (api_token/password sono EncryptedString, vedi nazgarr/models.py).
    crypto_module._fernet.cache_clear()

    engine = db_module.make_engine(str(tmp_path / "test.db"))
    db_module.migrate_legacy_media_path_id(engine)
    db_module.repair_dangling_media_file_legacy_fk(engine)
    db_module.migrate_legacy_run_log_phase_check(engine)
    db_module.migrate_legacy_upload_job(engine)
    db_module.apply_schema(engine)
    db_module.migrate_schema(engine)
    session_factory = db_module.make_session_factory(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        crypto_module._fernet.cache_clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    scan_root = tmp_path / "mnt"
    scan_root.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"disk_scan_root: {scan_root}\ndata_dir: {data_dir}\n")
    monkeypatch.setenv("CONFIG_PATH", str(config_path))
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    # crypto._fernet() è cachata per processo (lru_cache): senza pulirla qui,
    # il primo test che gira nella sessione pytest "vince" per tutti i test
    # successivi, anche se ciascuno imposta una APP_SECRET_KEY diversa —
    # nel container reale non serve, perché lì un processo = un avvio solo.
    crypto_module._fernet.cache_clear()

    from nazgarr import login_limiter
    from nazgarr.main import app

    login_limiter.reset()
    with TestClient(app) as test_client:
        test_client.scan_root = scan_root  # comodo per i test: root disponibile senza rileggere il config
        # Il login è obbligatorio: ogni test parte con l'account creato e il
        # token già negli header (i test del login usano anon_client).
        token = test_client.post("/api/auth/setup", json={
            "username": "admin", "password": "supersecret1", "setup_code": app.state.setup_code,
        }).json()["access_token"]
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client

    crypto_module._fernet.cache_clear()


@pytest.fixture
def anon_client(tmp_path, monkeypatch):
    """Un'istanza appena installata: nessun account, nessun token."""
    data_dir = tmp_path / "data"
    scan_root = tmp_path / "mnt"
    scan_root.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"disk_scan_root: {scan_root}\ndata_dir: {data_dir}\n")
    monkeypatch.setenv("CONFIG_PATH", str(config_path))
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    crypto_module._fernet.cache_clear()

    from nazgarr import login_limiter
    from nazgarr.main import app

    login_limiter.reset()
    with TestClient(app) as test_client:
        yield test_client

    crypto_module._fernet.cache_clear()
