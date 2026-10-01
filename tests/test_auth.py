from app import auth


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
