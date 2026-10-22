def test_get_unset_setting_returns_null_value(client):
    response = client.get("/api/settings/tmdb_api_key")

    assert response.status_code == 200
    assert response.json() == {"key": "tmdb_api_key", "value": None, "is_set": False}


def test_set_then_get_setting(client):
    put = client.put("/api/settings/upload_releaser_name", json={"value": "GRP"})
    assert put.status_code == 200
    assert put.json() == {"key": "upload_releaser_name", "value": "GRP", "is_set": True}

    get = client.get("/api/settings/upload_releaser_name")
    assert get.json() == {"key": "upload_releaser_name", "value": "GRP", "is_set": True}


def test_a_secret_setting_is_written_but_never_read_back(client):
    """Come i segreti di tracker, client e plugin: prima la chiave TMDB/TVDB
    tornava in chiaro a ogni sessione del browser (audit 2026-10-18)."""
    put = client.put("/api/settings/tmdb_api_key", json={"value": "abc123"})
    assert put.status_code == 200
    assert put.json() == {"key": "tmdb_api_key", "value": None, "is_set": True}
    assert client.get("/api/settings/tmdb_api_key").json() == {"key": "tmdb_api_key", "value": None, "is_set": True}
    assert "abc123" not in client.get("/api/settings/tmdb_api_key").text
    with client.app.state.session_factory() as session:
        from nazgarr.core import settings_repo

        assert settings_repo.get_setting(session, "tmdb_api_key") == "abc123"  # per chi la usa davvero
    assert client.put("/api/settings/tmdb_api_key", json={"value": ""}).json()["is_set"] is False


def test_set_overwrites_previous_value(client):
    client.put("/api/settings/tmdb_api_key", json={"value": "first"})
    client.put("/api/settings/tmdb_api_key", json={"value": "second"})

    with client.app.state.session_factory() as session:
        from nazgarr.core import settings_repo

        assert settings_repo.get_setting(session, "tmdb_api_key") == "second"


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
    assert client.get("/api/schedule").json() == {"cron": None, "enabled": False, "error": None}


def test_the_managed_keys_are_the_ones_their_modules_use():
    from nazgarr import scheduler
    from nazgarr.api import instances as instances_api
    from nazgarr.core import db_startup, settings_registry, startup_checks, updates
    from nazgarr.library import not_imported, resolution
    from nazgarr.plugins import switch
    from nazgarr.upload import file_names

    assert settings_registry.MANAGED_KEYS == {
        scheduler.SETTING_KEY, scheduler.LAST_SLOT_KEY, startup_checks._CANARY_KEY, switch.SETTING,
        updates.SEEN_KEY, updates.LAST_CHECK_KEY, resolution.IDENTITY_RULES_KEY, instances_api.LOCAL_NAME_SETTING,
        file_names.SETTING, not_imported.STATUS_SETTING, db_startup.LAST_BACKUP_KEY,
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


def test_a_key_that_is_not_a_setting_is_a_400_and_nothing_is_saved(client):
    """Prima PUT /api/settings/{key} salvava qualunque chiave: una nuova di
    stato interno di un modulo era scrivibile finché qualcuno non la
    aggiungeva a MANAGED_KEYS (audit 2026-10-18)."""
    from nazgarr.core.models import AppSetting

    response = client.put("/api/settings/not_a_setting", json={"value": "x"})
    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "setting_unknown", "params": {"key": "not_a_setting"}}
    assert client.get("/api/settings/not_a_setting").json()["detail"]["code"] == "setting_unknown"
    with client.app.state.session_factory() as session:
        assert session.get(AppSetting, "not_a_setting") is None
    # Lo stato dell'interfaccia è nel registro: si salva.
    assert client.put("/api/settings/onboarding_state", json={"value": '{"status":"done"}'}).status_code == 200
    assert client.put("/api/settings/tracker_filter", json={"value": "3"}).json()["value"] == "3"
    assert client.put("/api/settings/library_default_view", json={"value": "poster"}).status_code == 200
