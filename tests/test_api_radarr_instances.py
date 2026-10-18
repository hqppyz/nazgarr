def test_create_list_update_delete_radarr_instance(client):
    create = client.post(
        "/api/radarr-instances",
        json={"label": "Main Radarr", "base_url": "http://radarr:7878", "api_key": "secret"},
    )
    assert create.status_code == 201
    body = create.json()
    instance_id = body["id"]
    assert "api_key" not in body  # mai esposto in risposta
    assert "basic_auth_password" not in body
    assert body["priority"] == 0  # default applicato lato Python
    assert body["timeout_seconds"] == 15

    listed = client.get("/api/radarr-instances").json()
    assert any(i["id"] == instance_id for i in listed)

    update = client.patch(f"/api/radarr-instances/{instance_id}", json={"enabled": False})
    assert update.status_code == 200
    assert update.json()["enabled"] is False

    delete = client.delete(f"/api/radarr-instances/{instance_id}")
    assert delete.status_code == 204
    assert client.get("/api/radarr-instances").json() == []


def test_create_with_priority_timeout_and_basic_auth(client):
    create = client.post(
        "/api/radarr-instances",
        json={
            "label": "Behind proxy", "base_url": "http://radarr.internal", "api_key": "secret",
            "priority": 10, "timeout_seconds": 30,
            "basic_auth_username": "proxyuser", "basic_auth_password": "proxypass",
        },
    )
    assert create.status_code == 201
    body = create.json()
    assert body["priority"] == 10
    assert body["timeout_seconds"] == 30
    assert body["basic_auth_username"] == "proxyuser"
    assert "basic_auth_password" not in body


def test_timeout_outside_its_bounds_is_refused(client):
    """Un timeout negativo arrivava a httpx come valore non valido, e ogni
    chiamata all'istanza falliva senza dire perché (audit 2026-10-18)."""
    base = {"label": "x", "base_url": "http://radarr", "api_key": "k"}
    for value in (-5, 0, 301):
        assert client.post("/api/radarr-instances", json={**base, "timeout_seconds": value}).status_code == 422
        assert client.post("/api/radarr-instances/test", json={**base, "timeout_seconds": value}).status_code == 422
    instance_id = client.post("/api/radarr-instances", json=base).json()["id"]
    assert client.patch(f"/api/radarr-instances/{instance_id}", json={"timeout_seconds": -1}).status_code == 422
    assert client.patch(f"/api/radarr-instances/{instance_id}", json={"timeout_seconds": 300}).status_code == 200


def test_a_stored_timeout_that_is_not_positive_falls_back_to_the_default():
    """Una riga salvata prima dei limiti dell'API con un timeout negativo."""
    from types import SimpleNamespace

    from nazgarr.integrations.arr import DEFAULT_TIMEOUT_SECONDS, timeout_of

    assert [timeout_of(SimpleNamespace(timeout_seconds=v)) for v in (-5, 0, None, 40)] == [
        DEFAULT_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS, 40]


def test_clearing_basic_auth_username_removes_it(client):
    create = client.post(
        "/api/radarr-instances",
        json={
            "label": "x", "base_url": "http://radarr", "api_key": "k",
            "basic_auth_username": "user", "basic_auth_password": "pass",
        },
    )
    instance_id = create.json()["id"]

    update = client.patch(f"/api/radarr-instances/{instance_id}", json={"basic_auth_username": ""})
    assert update.json()["basic_auth_username"] is None


def test_test_connection_reports_error_on_unreachable_instance(client):
    create = client.post(
        "/api/radarr-instances",
        json={"label": "x", "base_url": "http://radarr.invalid.example", "api_key": "k", "timeout_seconds": 1},
    )
    instance_id = create.json()["id"]

    response = client.post(f"/api/radarr-instances/{instance_id}/test")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]


def test_stateless_test_connection_before_creating(client):
    """Il dialog "Add instance" può testare prima di salvare — nessun
    instance_id coinvolto."""
    response = client.post(
        "/api/radarr-instances/test",
        json={"base_url": "http://radarr.invalid.example", "api_key": "k", "timeout_seconds": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]


def test_supports_multiple_instances(client):
    client.post("/api/radarr-instances", json={"label": "4K", "base_url": "http://radarr-4k:7878", "api_key": "a"})
    client.post("/api/radarr-instances", json={"label": "SD", "base_url": "http://radarr-sd:7878", "api_key": "b"})

    listed = client.get("/api/radarr-instances").json()
    assert {i["label"] for i in listed} == {"4K", "SD"}


def test_get_radarr_instance_not_found_returns_coded_error(client):
    response = client.patch("/api/radarr-instances/999999", json={"label": "x"})
    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "radarr_instance_not_found", "params": {"id": 999999}}
