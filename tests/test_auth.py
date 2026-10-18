from nazgarr.web import auth


def test_hash_and_verify_password_roundtrip():
    hashed = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", hashed)
    assert not auth.verify_password("wrong password", hashed)


def test_verify_password_rejects_malformed_hash():
    assert not auth.verify_password("anything", "not-a-real-hash")


def test_create_and_decode_access_token_roundtrip(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    token = auth.create_access_token("admin")
    assert auth.decode_access_token(token) == "admin"


def test_decode_access_token_rejects_garbage(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    assert auth.decode_access_token("not-a-jwt") is None


def _setup(client, **extra):
    body = {"username": "admin", "password": "supersecret1", "setup_code": client.app.state.setup_code, **extra}
    return client.post("/api/auth/setup", json=body)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_everything_is_closed_until_the_account_exists(anon_client):
    # Prima era aperto: chiunque in rete aveva il pieno controllo.
    assert anon_client.get("/api/disks").status_code == 401
    assert anon_client.post("/api/reviews/1/approve").status_code == 401
    assert anon_client.get("/api/auth/status").json() == {"configured": False}


def test_setup_needs_the_one_time_code_from_the_log(anon_client):
    assert _setup(anon_client, setup_code="guess").status_code == 403
    response = _setup(anon_client)
    assert response.status_code == 201
    assert response.json()["username"] == "admin"
    assert anon_client.get("/api/disks", headers=_bearer(response.json()["access_token"])).status_code == 200
    assert anon_client.app.state.setup_code is None  # usato: non vale più


def test_the_setup_code_can_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(auth.SETUP_CODE_ENV, "my-known-code")
    assert auth.new_setup_code() == "my-known-code"
    monkeypatch.delenv(auth.SETUP_CODE_ENV)
    assert auth.new_setup_code() != auth.new_setup_code()


def test_setup_rejects_short_password(anon_client):
    assert _setup(anon_client, password="short").status_code == 400


def test_setup_twice_is_rejected(anon_client):
    code = anon_client.app.state.setup_code
    assert _setup(anon_client).status_code == 201
    assert anon_client.post("/api/auth/setup", json={
        "username": "other", "password": "supersecret2", "setup_code": code,
    }).status_code == 409


def test_protected_endpoint_requires_a_valid_token(anon_client):
    token = _setup(anon_client).json()["access_token"]
    assert anon_client.get("/api/disks").status_code == 401
    assert anon_client.get("/api/disks", headers=_bearer("garbage")).status_code == 401
    assert anon_client.get("/api/disks", headers=_bearer(token)).status_code == 200


def test_login(anon_client):
    creds = {"username": "admin", "password": "supersecret1"}
    assert anon_client.post("/api/auth/login", json=creds).status_code == 401
    _setup(anon_client)
    ok = anon_client.post("/api/auth/login", json={"username": "admin", "password": "supersecret1"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    for username, password in (("admin", "wrong-password"), ("root", "supersecret1")):
        bad = anon_client.post("/api/auth/login", json={"username": username, "password": password})
        assert bad.status_code == 401


def test_me(anon_client):
    token = _setup(anon_client).json()["access_token"]
    assert anon_client.get("/api/auth/me").status_code == 401
    assert anon_client.get("/api/auth/me", headers=_bearer(token)).json() == {"username": "admin"}


def test_change_password(anon_client):
    headers = _bearer(_setup(anon_client).json()["access_token"])
    wrong = {"current_password": "nope-nope", "new_password": "newsecret123"}
    assert anon_client.post("/api/auth/change-password", json=wrong, headers=headers).status_code == 401
    right = {"current_password": "supersecret1", "new_password": "newsecret123"}
    assert anon_client.post("/api/auth/change-password", json=right, headers=headers).status_code == 204
    new = {"username": "admin", "password": "newsecret123"}
    assert anon_client.post("/api/auth/login", json=new).status_code == 200


def test_changing_the_password_or_logging_out_everywhere_revokes_every_token(anon_client):
    old = _setup(anon_client).json()["access_token"]
    assert anon_client.get("/api/disks", headers=_bearer(old)).status_code == 200

    change = {"current_password": "supersecret1", "new_password": "newsecret123"}
    assert anon_client.post("/api/auth/change-password", json=change, headers=_bearer(old)).status_code == 204
    assert anon_client.get("/api/disks", headers=_bearer(old)).status_code == 401  # la sessione rubata è fuori

    new = anon_client.post("/api/auth/login", json={"username": "admin", "password": "newsecret123"}).json()
    token = new["access_token"]
    assert anon_client.get("/api/disks", headers=_bearer(token)).status_code == 200
    assert anon_client.post("/api/auth/logout-everywhere", headers=_bearer(token)).status_code == 204
    assert anon_client.get("/api/disks", headers=_bearer(token)).status_code == 401


def test_too_many_wrong_passwords_are_slowed_down(anon_client):
    from nazgarr.web import login_limiter

    _setup(anon_client)
    wrong = {"username": "admin", "password": "wrong-password"}
    for _ in range(login_limiter.MAX_FAILURES):
        assert anon_client.post("/api/auth/login", json=wrong).status_code == 401
    right = {"username": "admin", "password": "supersecret1"}
    blocked = anon_client.post("/api/auth/login", json=right)
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    login_limiter.reset()
    assert anon_client.post("/api/auth/login", json=right).status_code == 200


def test_the_window_forgets_old_failures():
    from nazgarr.web import login_limiter

    login_limiter.reset()
    for i in range(login_limiter.MAX_FAILURES):
        login_limiter.failed("1.2.3.4", now=100.0 + i)
    assert login_limiter.retry_after("1.2.3.4", now=110.0) is not None
    assert login_limiter.retry_after("1.2.3.4", now=100.0 + login_limiter.WINDOW_SECONDS + 1) is None


def test_a_setup_code_with_accents_is_just_wrong(anon_client):
    # compare_digest su str non ASCII sollevava TypeError: un 500, non un 403.
    assert _setup(anon_client, setup_code="é-non-ascii").status_code == 403
    assert _setup(anon_client).status_code == 201


def test_a_non_ascii_setup_code_from_the_environment_still_works(anon_client):
    anon_client.app.state.setup_code = "codice-città"
    assert _setup(anon_client, setup_code="codice-città").status_code == 201


def test_attempts_arriving_together_are_counted_before_the_password_check():
    # Prima controllo e registrazione stavano ai due lati del PBKDF2: 38 tentativi
    # su 60 partiti insieme passavano, invece di 5 (audit 2026-10-18).
    import threading

    from nazgarr.web import login_limiter

    login_limiter.reset()
    barrier = threading.Barrier(40)
    passed = []

    def attempt():
        barrier.wait()
        try:
            login_limiter.reserve("172.18.0.5")
            passed.append(True)
        except login_limiter.TooManyAttempts:
            pass

    threads = [threading.Thread(target=attempt) for _ in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(passed) == login_limiter.MAX_FAILURES
    login_limiter.reset()


def test_a_released_attempt_does_not_count_and_old_addresses_are_forgotten(monkeypatch):
    from nazgarr.web import login_limiter

    login_limiter.reset()
    stamp = login_limiter.reserve("1.2.3.4", now=100.0)
    login_limiter.release("1.2.3.4", stamp)
    assert "1.2.3.4" not in login_limiter._failures  # vuota: sparisce

    login_limiter.failed("5.6.7.8", now=100.0)
    assert login_limiter.retry_after("5.6.7.8", now=100.0 + login_limiter.WINDOW_SECONDS + 1) is None
    assert "5.6.7.8" not in login_limiter._failures

    monkeypatch.setattr(login_limiter, "MAX_KEYS", 3)
    for i in range(10):
        login_limiter.failed(f"10.0.0.{i}", now=200.0 + i)
    assert list(login_limiter._failures) == ["10.0.0.7", "10.0.0.8", "10.0.0.9"]
    login_limiter.reset()


def test_wrong_current_passwords_do_not_lock_the_login(anon_client):
    from nazgarr.web import login_limiter

    headers = _bearer(_setup(anon_client).json()["access_token"])
    wrong = {"current_password": "nope-nope", "new_password": "newsecret123"}
    for _ in range(login_limiter.MAX_FAILURES):
        assert anon_client.post("/api/auth/change-password", json=wrong, headers=headers).status_code == 401
    assert anon_client.post("/api/auth/change-password", json=wrong, headers=headers).status_code == 429
    login = {"username": "admin", "password": "supersecret1"}
    assert anon_client.post("/api/auth/login", json=login).status_code == 200


def test_a_too_short_new_password_is_not_a_wrong_attempt(anon_client):
    from nazgarr.web import login_limiter

    headers = _bearer(_setup(anon_client).json()["access_token"])
    short = {"current_password": "supersecret1", "new_password": "short"}
    for _ in range(login_limiter.MAX_FAILURES + 1):
        assert anon_client.post("/api/auth/change-password", json=short, headers=headers).status_code == 400


def _old_hash(password, iterations=260_000):
    import hashlib

    salt = "00" * 16
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def test_a_weaker_password_hash_is_redone_at_the_next_login(anon_client):
    from nazgarr.core import settings_repo

    token = _setup(anon_client).json()["access_token"]
    with anon_client.app.state.session_factory() as session:
        settings_repo.set_setting(session, "auth_password_hash", _old_hash("supersecret1"))
    assert auth.needs_rehash(_old_hash("supersecret1"))

    login = {"username": "admin", "password": "supersecret1"}
    assert anon_client.post("/api/auth/login", json=login).status_code == 200
    with anon_client.app.state.session_factory() as session:
        stored = settings_repo.get_setting(session, "auth_password_hash")
    assert stored.split("$")[1] == str(auth._PBKDF2_ITERATIONS) and not auth.needs_rehash(stored)
    assert anon_client.post("/api/auth/login", json=login).status_code == 200
    assert anon_client.get("/api/disks", headers=_bearer(token)).status_code == 200  # nessuno buttato fuori


def _token(payload):
    import os

    import jwt

    return jwt.encode(payload, os.environ["APP_SECRET_KEY"], algorithm="HS256")


def test_a_token_of_another_installation_with_the_same_key_is_refused(anon_client):
    import time

    token = _setup(anon_client).json()["access_token"]
    assert anon_client.get("/api/disks", headers=_bearer(token)).status_code == 200
    other = _token({"sub": "admin", "ver": "1", "exp": int(time.time()) + 3600, "aud": "nazgarr:another-one"})
    assert anon_client.get("/api/disks", headers=_bearer(other)).status_code == 401
    no_expiry = _token({"sub": "admin", "ver": "1"})
    assert anon_client.get("/api/disks", headers=_bearer(no_expiry)).status_code == 401


def test_tokens_from_before_the_audience_last_until_they_expire(anon_client):
    import time

    from nazgarr.core import settings_repo

    _setup(anon_client)
    legacy = _token({"sub": "admin", "ver": "1", "exp": int(time.time()) + 3600})
    # Installazione nuova: nessun token di prima da lasciar valere.
    assert anon_client.get("/api/disks", headers=_bearer(legacy)).status_code == 401

    with anon_client.app.state.session_factory() as session:  # come dopo l'aggiornamento
        settings_repo.set_setting(session, "auth_legacy_tokens_until", str(int(time.time()) + 7200))
    assert anon_client.get("/api/disks", headers=_bearer(legacy)).status_code == 200
    too_long = _token({"sub": "admin", "ver": "1", "exp": int(time.time()) + 3 * 3600})
    assert anon_client.get("/api/disks", headers=_bearer(too_long)).status_code == 401


def test_an_upgrade_keeps_the_sessions_of_an_existing_account(db_session):
    from nazgarr.core import settings_repo

    settings_repo.set_setting(db_session, "auth_username", "admin")
    settings_repo.set_setting(db_session, "auth_password_hash", _old_hash("supersecret1"))
    audience = auth.token_audience(db_session)
    assert audience.startswith("nazgarr:") and auth.token_audience(db_session) == audience
    assert auth._legacy_tokens_until(db_session) > 0
