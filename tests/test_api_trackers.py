def test_create_list_update_delete_tracker(client):
    create = client.post(
        "/api/trackers",
        json={"label": "ITT", "adapter_type": "unit3d", "base_url": "https://itt.example", "api_token": "secret"},
    )
    assert create.status_code == 201
    tracker_id = create.json()["id"]
    assert "api_token" not in create.json()  # mai esposto in risposta

    listed = client.get("/api/trackers").json()
    assert any(t["id"] == tracker_id for t in listed)

    update = client.patch(f"/api/trackers/{tracker_id}", json={"enabled": False})
    assert update.status_code == 200
    assert update.json()["enabled"] is False

    delete = client.delete(f"/api/trackers/{tracker_id}")
    assert delete.status_code == 204
    assert client.get("/api/trackers").json() == []


def test_rejects_unsupported_adapter_type(client):
    response = client.post(
        "/api/trackers",
        json={"label": "x", "adapter_type": "gazelle", "base_url": "https://x.example", "api_token": "t"},
    )
    assert response.status_code == 400


def test_tracker_client_can_be_set_and_cleared(client):
    created = client.post("/api/trackers", json={
        "label": "ITT", "adapter_type": "unit3d", "base_url": "https://t.example", "api_token": "x",
        "torrent_client_id": 3,
    }).json()
    assert created["torrent_client_id"] == 3

    kept = client.patch(f"/api/trackers/{created['id']}", json={"label": "ITT 2"}).json()
    assert kept["torrent_client_id"] == 3
    cleared = client.patch(f"/api/trackers/{created['id']}", json={"torrent_client_id": None}).json()
    assert cleared["torrent_client_id"] is None


def test_tracker_icon_and_upload_profile_summary(client, monkeypatch, tmp_path):
    from app.api import trackers as trackers_api

    tracker_id = client.post("/api/trackers", json={
        "label": "ITT", "adapter_type": "unit3d", "base_url": "https://itt.example", "api_token": "x",
    }).json()["id"]
    assert client.get("/api/trackers").json()[0]["upload_profile"] is None

    client.post(f"/api/trackers/{tracker_id}/upload-profile", json={"profile_key": "itt"})
    summary = client.get("/api/trackers").json()[0]["upload_profile"]
    assert summary["source_profile_key"] == "itt" and summary["naming_version"] >= 1

    monkeypatch.setattr(trackers_api.tracker_icons, "fetch_icon", lambda data_dir, tid, base_url: None)
    assert client.get(f"/api/trackers/{tracker_id}/icon").status_code == 404
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"\\x89PNG")
    monkeypatch.setattr(trackers_api.tracker_icons, "fetch_icon", lambda data_dir, tid, base_url: str(icon))
    assert client.get(f"/api/trackers/{tracker_id}/icon").status_code == 200


def test_the_seeding_requirement_is_optional_and_editable(client):
    created = client.post("/api/trackers", json={
        "label": "ITT", "adapter_type": "unit3d", "base_url": "https://t.example", "api_token": "x",
    }).json()
    assert (created["min_seed_time_seconds"], created["min_ratio"], created["seed_rule"]) == (None, None, "any")

    url = f"/api/trackers/{created['id']}"
    set_ = client.patch(url, json={"min_seed_time_seconds": 259200, "min_ratio": 1.0, "seed_rule": "all"}).json()
    assert (set_["min_seed_time_seconds"], set_["min_ratio"], set_["seed_rule"]) == (259200, 1.0, "all")
    kept = client.patch(url, json={"label": "ITT 2"}).json()
    assert kept["min_ratio"] == 1.0
    cleared = client.patch(url, json={"min_ratio": None}).json()
    assert (cleared["min_ratio"], cleared["min_seed_time_seconds"]) == (None, 259200)
    assert client.patch(url, json={"min_ratio": -1}).status_code == 422
    assert client.patch(url, json={"seed_rule": "maybe"}).status_code == 422
