import base64
import os

import pytest

from nazgarr.core import crypto as crypto_module
from nazgarr.core import startup_checks


def _random_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


@pytest.fixture(autouse=True)
def _clear_fernet_cache():
    # Stesso motivo di tests/conftest.py::client — crypto._fernet() è cachata
    # per processo, va pulita tra un test e l'altro qui dentro.
    crypto_module._fernet.cache_clear()
    yield
    crypto_module._fernet.cache_clear()


def test_first_boot_writes_the_canary(db_session, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", _random_key())

    startup_checks.verify_secret_key(db_session)  # non deve sollevare

    from nazgarr.core.models import AppSetting

    row = db_session.get(AppSetting, startup_checks._CANARY_KEY)
    assert row is not None


def test_same_key_on_second_boot_succeeds(db_session, monkeypatch):
    key = _random_key()
    monkeypatch.setenv("APP_SECRET_KEY", key)
    startup_checks.verify_secret_key(db_session)

    crypto_module._fernet.cache_clear()  # simula un nuovo avvio del processo
    startup_checks.verify_secret_key(db_session)  # non deve sollevare


def test_changed_key_on_second_boot_raises(db_session, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", _random_key())
    startup_checks.verify_secret_key(db_session)

    crypto_module._fernet.cache_clear()
    monkeypatch.setenv("APP_SECRET_KEY", _random_key())  # chiave diversa

    with pytest.raises(startup_checks.SecretKeyMismatchError):
        startup_checks.verify_secret_key(db_session)


def test_every_connection_waits_for_a_busy_database(db_session):
    from sqlalchemy import text

    assert db_session.execute(text("PRAGMA busy_timeout")).scalar() == 30000
    assert db_session.execute(text("PRAGMA journal_mode")).scalar() == "wal"
