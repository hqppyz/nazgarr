import base64
import os
import socket

import pytest
from fastapi.testclient import TestClient

from nazgarr.core import crypto as crypto_module
from nazgarr.core import db as db_module
from nazgarr.core import migrations

_real_getaddrinfo = socket.getaddrinfo


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "background: il test usa lo scheduler e il worker di upload veri, avviati (client, anon_client)")


def _offline_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Indirizzi IP (anche nelle forme decimali/esadecimali) e localhost si
    risolvono come sempre, ogni altro nome come un nome che non esiste."""
    try:
        return _real_getaddrinfo(host, port, family, type, proto, flags | socket.AI_NUMERICHOST)
    except socket.gaierror:
        if host in ("localhost", b"localhost"):
            return _real_getaddrinfo(host, port, family, type, proto, flags)
        raise


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """Nessun test dipende dal DNS (audit 2026-10-18): net_guard e la
    validazione degli URL risolvevano davvero t.example, qbit, evil... Un
    test che ha bisogno di nomi li sostituisce col suo monkeypatch
    (test_instances, test_net_guard). I test sui client veri in Docker
    (NAZGARR_IT_CLIENTS=1) usano il DNS vero."""
    if not os.environ.get("NAZGARR_IT_CLIENTS"):
        monkeypatch.setattr(socket, "getaddrinfo", _offline_getaddrinfo)


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    # Stesso motivo del fixture `client` sotto: crypto._fernet() è cachata per
    # processo, va pulita qui altrimenti un test precedente nella stessa
    # sessione pytest "vince" la chiave per chi crea un Tracker/TorrentClient
    # (api_token/password sono EncryptedString, vedi nazgarr/core/models.py).
    crypto_module._fernet.cache_clear()

    engine = db_module.make_engine(str(tmp_path / "test.db"))
    migrations.upgrade(engine)  # come all'avvio dell'app
    session_factory = db_module.make_session_factory(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        crypto_module._fernet.cache_clear()


@pytest.fixture
def _quiet_background(request, monkeypatch):
    """L'app dei test (client, anon_client) non fa lavoro in background
    (audit 2026-10-18): lo scheduler parte in pausa (i job ci sono, get_job
    e reschedule funzionano, nessuno gira) e il worker di upload non riprende
    i job interrotti. Prima ogni test delle API girava con i thread veri: un
    test lento, una pausa nel debugger o un cron al minuto facevano girare
    job veri sul DB del test, insieme al test. Un test che li vuole avviati
    si segna con @pytest.mark.background; chi vuole un job lo chiama
    direttamente (come test_season_pack con _reconcile_between_runs)."""
    if request.node.get_closest_marker("background"):
        return
    from nazgarr import main, scheduler
    from nazgarr.upload.worker import UploadWorker

    build = scheduler.build_scheduler

    def paused_scheduler(*args, **kwargs):
        built = build(*args, **kwargs)
        start = built.start
        built.start = lambda *a, **kw: start(paused=True)
        return built

    class QuietUploadWorker(UploadWorker):
        def resume(self) -> None:
            pass

    monkeypatch.setattr(scheduler, "build_scheduler", paused_scheduler)
    monkeypatch.setattr(main, "UploadWorker", QuietUploadWorker)


@pytest.fixture
def client(tmp_path, monkeypatch, _quiet_background):
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

    from nazgarr.main import app
    from nazgarr.web import login_limiter

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
def anon_client(tmp_path, monkeypatch, _quiet_background):
    """Un'istanza appena installata: nessun account, nessun token."""
    data_dir = tmp_path / "data"
    scan_root = tmp_path / "mnt"
    scan_root.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"disk_scan_root: {scan_root}\ndata_dir: {data_dir}\n")
    monkeypatch.setenv("CONFIG_PATH", str(config_path))
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    crypto_module._fernet.cache_clear()

    from nazgarr.main import app
    from nazgarr.web import login_limiter

    login_limiter.reset()
    with TestClient(app) as test_client:
        yield test_client

    crypto_module._fernet.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_tracker_state():
    """Rate limit e cache delle ricerche dei tracker sono condivisi nel
    processo (nazgarr/adapters/tracker/base.py): mai fra un test e l'altro."""
    from nazgarr.adapters.tracker.base import reset_shared_state
    from nazgarr.library import episode_orders
    from nazgarr.library import mediainfo as mediainfo_util

    def clear():
        reset_shared_state()
        mediainfo_util.clear_cache()  # per inode: mai una voce di un file di un altro test
        episode_orders.clear_cache()

    clear()
    yield
    clear()
