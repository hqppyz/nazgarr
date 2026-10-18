def test_get_unset_setting_returns_null_value(client):
    response = client.get("/api/settings/tmdb_api_key")

    assert response.status_code == 200
    assert response.json() == {"key": "tmdb_api_key", "value": None}


def test_set_then_get_setting(client):
    put = client.put("/api/settings/tmdb_api_key", json={"value": "abc123"})
    assert put.status_code == 200
    assert put.json() == {"key": "tmdb_api_key", "value": "abc123"}

    get = client.get("/api/settings/tmdb_api_key")
    assert get.json() == {"key": "tmdb_api_key", "value": "abc123"}


def test_set_overwrites_previous_value(client):
    client.put("/api/settings/tmdb_api_key", json={"value": "first"})
    client.put("/api/settings/tmdb_api_key", json={"value": "second"})

    response = client.get("/api/settings/tmdb_api_key")
    assert response.json()["value"] == "second"


def test_exclusion_presets_available_lists_known_presets(client):
    response = client.get("/api/settings/exclusion-presets/available")
    assert response.status_code == 200
    keys = {p["key"] for p in response.json()}
    assert {"scene_junk", "qbittorrent_incomplete", "utorrent_incomplete", "bitcomet_incomplete"} <= keys


def test_keys_with_their_own_endpoint_are_never_written_from_here(client):
    """Un schedule_cron scritto da qui saltava la validazione di
    /api/schedule e fermava l'avvio successivo (audit 2026-10-18)."""
    from nazgarr.core import settings_registry

    for key in settings_registry.MANAGED_KEYS:
        response = client.put(f"/api/settings/{key}", json={"value": "every night please"})
        assert response.status_code == 403, key
        assert response.json()["detail"] == {"code": "setting_protected", "params": {"key": key}}
    # Si leggono ancora.
    assert client.get("/api/settings/schedule_cron").status_code == 200
    assert client.get("/api/schedule").json() == {"cron": None, "enabled": False}


def test_the_managed_keys_are_the_ones_their_modules_use():
    from nazgarr import scheduler
    from nazgarr.api import instances as instances_api
    from nazgarr.core import settings_registry, startup_checks, updates
    from nazgarr.library import not_imported, resolution
    from nazgarr.plugins import switch
    from nazgarr.upload import file_names

    assert settings_registry.MANAGED_KEYS == {
        scheduler.SETTING_KEY, startup_checks._CANARY_KEY, switch.SETTING, updates.SEEN_KEY, updates.LAST_CHECK_KEY,
        resolution.IDENTITY_RULES_KEY, instances_api.LOCAL_NAME_SETTING, file_names.SETTING,
        not_imported.STATUS_SETTING,
    }
    assert not settings_registry.MANAGED_KEYS & set(settings_registry.REGISTRY)


def test_a_free_value_has_a_length_limit(client):
    from nazgarr.core import settings_registry

    long = "x" * (settings_registry.MAX_VALUE_LENGTH + 1)
    response = client.put("/api/settings/upload_description_header", json={"value": long})
    assert response.status_code == 400 and response.json()["detail"]["code"] == "setting_invalid_value"
    assert client.put("/api/settings/upload_description_header", json={"value": "[b]hi[/b]"}).status_code == 200


def test_only_secret_keys_are_decrypted(db_session):
    """Un "enc:" su una chiave qualunque rompeva ogni sua lettura (per
    exclusion_patterns ogni vista della libreria); un segreto che comincia per
    "enc:" restava in chiaro e poi non si leggeva più."""
    from nazgarr.core import settings_repo
    from nazgarr.core.models import AppSetting

    settings_repo.set_setting(db_session, "exclusion_patterns", "enc:whatever")
    assert settings_repo.get_setting(db_session, "exclusion_patterns") == "enc:whatever"
    settings_repo.set_setting(db_session, "tmdb_api_key", "enc:looks-encrypted")
    stored = db_session.get(AppSetting, "tmdb_api_key").value
    assert stored != "enc:looks-encrypted" and "looks-encrypted" not in stored
    assert settings_repo.get_setting(db_session, "tmdb_api_key") == "enc:looks-encrypted"
