def _create_tracker(client):
    response = client.post(
        "/api/trackers",
        json={"label": "t", "adapter_type": "unit3d", "base_url": "https://t.example", "api_token": "x"},
    )
    return response.json()["id"]


def test_list_bundled_profiles(client):
    response = client.get("/api/trackers/upload-profiles/bundled")

    assert response.status_code == 200
    profiles = response.json()
    keys = {p["key"] for p in profiles}
    assert "itt" in keys
    itt = next(p for p in profiles if p["key"] == "itt")
    assert itt["base_url"] == "https://itatorrents.xyz"


def test_create_upload_profile_from_bundled_key(client):
    tracker_id = _create_tracker(client)

    response = client.post(f"/api/trackers/{tracker_id}/upload-profile", json={"profile_key": "itt"})

    assert response.status_code == 201
    body = response.json()
    assert body["tracker_id"] == tracker_id
    assert body["source_profile_key"] == "itt"
    assert body["category_id_map"]["movie"] == 1


def test_create_upload_profile_custom(client):
    tracker_id = _create_tracker(client)

    response = client.post(f"/api/trackers/{tracker_id}/upload-profile", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["source_profile_key"] is None
    assert body["category_id_map"] == {}


def test_create_upload_profile_duplicate_rejected(client):
    tracker_id = _create_tracker(client)
    client.post(f"/api/trackers/{tracker_id}/upload-profile", json={"profile_key": "itt"})

    response = client.post(f"/api/trackers/{tracker_id}/upload-profile", json={"profile_key": "itt"})

    assert response.status_code == 409


def test_create_upload_profile_unknown_bundled_key_rejected(client):
    tracker_id = _create_tracker(client)

    response = client.post(f"/api/trackers/{tracker_id}/upload-profile", json={"profile_key": "does-not-exist"})

    assert response.status_code == 400


def test_get_upload_profile_404_when_missing(client):
    tracker_id = _create_tracker(client)

    response = client.get(f"/api/trackers/{tracker_id}/upload-profile")

    assert response.status_code == 404


def test_patch_upload_profile_updates_fields(client):
    tracker_id = _create_tracker(client)
    client.post(f"/api/trackers/{tracker_id}/upload-profile", json={"profile_key": "itt"})

    response = client.patch(
        f"/api/trackers/{tracker_id}/upload-profile",
        json={"default_anonymous": True, "description_template": "custom {{ mediainfo }}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["default_anonymous"] is True
    assert body["description_template"] == "custom {{ mediainfo }}"
    assert body["category_id_map"]["movie"] == 1  # invariato


def test_delete_upload_profile(client):
    tracker_id = _create_tracker(client)
    client.post(f"/api/trackers/{tracker_id}/upload-profile", json={"profile_key": "itt"})

    response = client.delete(f"/api/trackers/{tracker_id}/upload-profile")

    assert response.status_code == 204
    assert client.get(f"/api/trackers/{tracker_id}/upload-profile").status_code == 404


def test_naming_rules_edit_marks_them_customized_and_update_restores_bundled(client):
    tracker_id = client.post("/api/trackers", json={
        "label": "ITT", "adapter_type": "unit3d", "base_url": "https://itt.example", "api_token": "x",
    }).json()["id"]
    created = client.post(f"/api/trackers/{tracker_id}/upload-profile", json={"profile_key": "itt"}).json()
    assert created["naming_version"] >= 1 and created["naming_customized"] is False
    rules = created["naming_rules"]

    edited = client.patch(f"/api/trackers/{tracker_id}/upload-profile",
                          json={"naming_rules": {**rules, "sdr_label": "SDR"}}).json()
    assert edited["naming_customized"] is True and edited["naming_rules"]["sdr_label"] == "SDR"

    restored = client.post(f"/api/trackers/{tracker_id}/upload-profile/naming/update").json()
    assert restored["naming_customized"] is False and restored["naming_rules"] == rules


def test_naming_preview_uses_an_example_without_uploads(client):
    tracker_id = client.post("/api/trackers", json={
        "label": "ITT", "adapter_type": "unit3d", "base_url": "https://itt.example", "api_token": "x",
    }).json()["id"]
    created = client.post(f"/api/trackers/{tracker_id}/upload-profile", json={"profile_key": "itt"}).json()
    rules = created["naming_rules"]

    preview = client.post(f"/api/trackers/{tracker_id}/upload-profile/naming/preview", json={"naming_rules": {
        **rules, "templates": {**rules["templates"], "REMUX": "{title} {year} {resolution} {audio_codec} {group}"},
    }}).json()

    assert preview["sample"]["kind"] == "example"
    assert preview["names"]["REMUX"] == "Dune: Part Two 2024 2160p TrueHD-GRP"
    assert preview["variables"]["audio_all"] == "TrueHD 7.1 Atmos DD+ 5.1"
