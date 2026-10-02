import httpx

import nazgarr.api.sonarr_instances as sonarr_instances_module


def test_create_list_update_delete_sonarr_instance(client):
    create = client.post(
        "/api/sonarr-instances",
        json={"label": "Main Sonarr", "base_url": "http://sonarr:8989", "api_key": "secret"},
    )
    assert create.status_code == 201
    body = create.json()
    instance_id = body["id"]
    assert "api_key" not in body  # mai esposto in risposta
    assert body["priority"] == 0
    assert body["timeout_seconds"] == 15

    listed = client.get("/api/sonarr-instances").json()
    assert any(i["id"] == instance_id for i in listed)

    update = client.patch(f"/api/sonarr-instances/{instance_id}", json={"enabled": False})
    assert update.status_code == 200
    assert update.json()["enabled"] is False

    delete = client.delete(f"/api/sonarr-instances/{instance_id}")
    assert delete.status_code == 204
    assert client.get("/api/sonarr-instances").json() == []


def test_supports_multiple_instances(client):
    client.post(
        "/api/sonarr-instances", json={"label": "Anime", "base_url": "http://sonarr-anime:8989", "api_key": "a"}
    )
    client.post("/api/sonarr-instances", json={"label": "TV", "base_url": "http://sonarr-tv:8989", "api_key": "b"})

    listed = client.get("/api/sonarr-instances").json()
    assert {i["label"] for i in listed} == {"Anime", "TV"}


def test_get_sonarr_instance_not_found_returns_coded_error(client):
    response = client.patch("/api/sonarr-instances/999999", json={"label": "x"})
    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "sonarr_instance_not_found", "params": {"id": 999999}}


def test_test_connection_reports_ok_with_version(client, monkeypatch):
    def fake_get(url, headers=None, auth=None, timeout=None):
        assert headers["X-Api-Key"] == "secret"
        return httpx.Response(200, json={"version": "4.0.9"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(sonarr_instances_module.httpx, "get", fake_get)

    create = client.post(
        "/api/sonarr-instances", json={"label": "x", "base_url": "http://sonarr", "api_key": "secret"}
    )
    instance_id = create.json()["id"]

    response = client.post(f"/api/sonarr-instances/{instance_id}/test")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "4.0.9", "error": None}


def test_stateless_test_connection_before_creating(client, monkeypatch):
    """Il dialog "Add instance" può testare prima di salvare — nessun
    instance_id coinvolto, i valori vengono dal form."""

    def fake_get(url, headers=None, auth=None, timeout=None):
        assert headers["X-Api-Key"] == "draft-key"
        return httpx.Response(200, json={"version": "4.0.9"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(sonarr_instances_module.httpx, "get", fake_get)

    response = client.post(
        "/api/sonarr-instances/test", json={"base_url": "http://sonarr:8989", "api_key": "draft-key"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "4.0.9", "error": None}
