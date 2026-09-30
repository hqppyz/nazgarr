"""API key (app/api_keys.py): due livelli, e mai per gestire le chiavi."""


def _login(client):
    token = client.post("/api/auth/setup", json={"username": "admin", "password": "supersecret1"}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


def _key(client, auth, level, name="script"):
    response = client.post("/api/api-keys", json={"name": name, "level": level}, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def test_read_and_write_keys(client):
    auth = _login(client)
    read, write = _key(client, auth, "read"), _key(client, auth, "write")
    assert read["key"].startswith("nzg_") and read["prefix"] == read["key"][:12]

    assert client.get("/api/trackers").status_code == 401  # senza niente, con il login attivo
    assert client.get("/api/trackers", headers={"X-Api-Key": read["key"]}).status_code == 200
    body = {"label": "t", "adapter_type": "unit3d", "base_url": "https://t.example", "api_token": "x"}
    assert client.post("/api/trackers", json=body, headers={"X-Api-Key": read["key"]}).status_code == 403
    assert client.post("/api/trackers", json=body, headers={"X-Api-Key": write["key"]}).status_code == 201
    assert client.get("/api/trackers", headers={"X-Api-Key": "nzg_nope"}).status_code == 401


def test_a_key_is_shown_once_and_can_be_revoked(client):
    auth = _login(client)
    created = _key(client, auth, "read", name="grafana")

    listed = client.get("/api/api-keys", headers=auth)
    assert created["key"] not in listed.text and "key_hash" not in listed.text
    assert [k["name"] for k in listed.json()] == ["grafana"]

    revoked = client.post(f"/api/api-keys/{created['id']}/revoke", headers=auth).json()
    assert revoked["revoked_at"] is not None
    assert client.get("/api/trackers", headers={"X-Api-Key": created["key"]}).status_code == 401


def test_a_key_cannot_manage_keys(client):
    auth = _login(client)
    write = _key(client, auth, "write")

    headers = {"X-Api-Key": write["key"]}
    assert client.get("/api/api-keys", headers=headers).status_code == 403
    assert client.post("/api/api-keys", json={"name": "more", "level": "write"}, headers=headers).status_code == 403


def test_a_wrong_key_is_rejected_even_without_a_login(client):
    # Nessun login configurato: l'app è aperta, ma una chiave sbagliata no.
    assert client.get("/api/trackers").status_code == 200
    assert client.get("/api/trackers", headers={"X-Api-Key": "nzg_wrong"}).status_code == 401


def test_invalid_requests(client):
    auth = _login(client)
    assert client.post("/api/api-keys", json={"name": " ", "level": "read"}, headers=auth).status_code == 400
    assert client.post("/api/api-keys", json={"name": "x", "level": "admin"}, headers=auth).status_code == 400
