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
                          json={"naming_rules": {**rules, "sdr_label": "STD"}}).json()
    assert edited["naming_customized"] is True and edited["naming_rules"]["sdr_label"] == "STD"

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
    # Il tracker ha preso l'italiano dal profilo ITT: titolo localizzato.
    assert preview["names"]["REMUX"] == "Dune - Parte due 2024 2160p TrueHD-FraMeSToR"
    assert preview["variables"]["audio_all"] == "TrueHD 7.1 DD+ 5.1 DTS-HD MA 5.1 Atmos"
    names = {example["key"]: example["name"] for example in preview["examples"]}
    assert set(names) == {"uhd_remux", "fhd_encode", "web_subbed", "series"}
    assert " 1080p FullHD NF WEB-DL " in names["web_subbed"] and " SUBS ITA " in names["web_subbed"]
    assert names["series"].startswith("Emberfall - Le terre di cenere S02 2160p UHD AMZN WEB-DL")
    # Ogni esempio col suo pattern: il remux quello per i REMUX appena cambiato.
    assert names["uhd_remux"] == preview["names"]["REMUX"]
    assert " 1080p FullHD BluRay " in names["fhd_encode"]


def test_a_tracker_at_a_bundled_address_gets_its_upload_profile(client):
    body = {"label": "ITT", "adapter_type": "unit3d", "api_token": "x"}
    itt = client.post("/api/trackers", json={**body, "base_url": "https://www.itatorrents.xyz/"}).json()
    assert itt["upload_profile"]["source_profile_key"] == "itt"
    assert itt["language"] == "it"

    other = client.post("/api/trackers", json={**body, "label": "Other", "base_url": "https://other.example"}).json()
    assert other["upload_profile"] is None

    none = client.post("/api/trackers", json={**body, "label": "ITT 2", "base_url": "https://itatorrents.xyz",
                                              "upload_profile": "none"}).json()
    assert none["upload_profile"] is None

    chosen = client.post("/api/trackers", json={**body, "label": "Mirror", "base_url": "https://mirror.example",
                                                "upload_profile": "itt"}).json()
    assert chosen["upload_profile"]["source_profile_key"] == "itt"

    before = len(client.get("/api/trackers").json())
    bad = client.post("/api/trackers", json={**body, "label": "Bad", "base_url": "https://bad.example",
                                             "upload_profile": "nope"})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "bundled_profile_not_found"
    assert len(client.get("/api/trackers").json()) == before  # niente tracker a metà


def test_an_upload_profile_can_be_restored_from_the_bundled_one(client):
    tracker_id = client.post("/api/trackers", json={
        "label": "ITT", "adapter_type": "unit3d", "base_url": "https://itatorrents.xyz", "api_token": "x",
    }).json()["id"]
    original = client.get(f"/api/trackers/{tracker_id}/upload-profile").json()
    client.patch(f"/api/trackers/{tracker_id}/upload-profile", json={
        "type_id_map": {"REMUX": 999}, "description_template": "mine", "default_anonymous": True,
        "naming_rules": {**original["naming_rules"], "sdr_label": "STD"},
    })

    restored = client.post(f"/api/trackers/{tracker_id}/upload-profile/restore", json={}).json()
    for key in ("type_id_map", "description_template", "default_anonymous", "naming_rules"):
        assert restored[key] == original[key], key
    assert restored["naming_customized"] is False

    # Un profilo custom vuoto diventa quello scelto.
    other = client.post("/api/trackers", json={
        "label": "Other", "adapter_type": "unit3d", "base_url": "https://other.example", "api_token": "x",
    }).json()["id"]
    client.post(f"/api/trackers/{other}/upload-profile", json={"profile_key": None})
    missing = client.post(f"/api/trackers/{other}/upload-profile/restore", json={})
    assert missing.status_code == 400
    chosen = client.post(f"/api/trackers/{other}/upload-profile/restore", json={"profile_key": "itt"}).json()
    assert chosen["source_profile_key"] == "itt" and chosen["type_id_map"] == original["type_id_map"]
