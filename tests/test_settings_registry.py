import pytest

from nazgarr import settings_registry, settings_repo
from nazgarr.settings_registry import SettingValueError, validate


@pytest.mark.parametrize(("key", "value", "saved"), [
    ("verify_before_execute", " Yes ", "true"),
    ("verify_before_execute", "off", "false"),
    ("confidence_threshold_auto_media_to_torrent", "0.9", "0.9"),
    ("rematch_interval_days", "7", "7"),
    ("upload_single_file_folder", "Remove", "remove"),
    ("upload_screenshot_count", "", ""),  # mai impostata: il default
    ("ui_timezone", "Europe/Rome", "Europe/Rome"),  # non nel registro: com'è
])
def test_validate_normalizes_known_settings(key, value, saved):
    assert validate(key, value) == saved


@pytest.mark.parametrize(("key", "value"), [
    ("verify_before_execute", "maybe"),
    ("confidence_threshold_auto_media_to_torrent", "95"),
    ("upload_screenshot_count", "40"),
    ("upload_single_file_folder", "delete"),
    ("rematch_interval_days", "-1"),
])
def test_validate_refuses_values_out_of_range(key, value):
    with pytest.raises(SettingValueError):
        validate(key, value)


def test_typed_getters_use_the_default_and_read_booleans_one_way(db_session):
    assert settings_registry.get_bool(db_session, "verify_before_execute") is True  # default
    settings_repo.set_setting(db_session, "verify_before_execute", "no")
    # Prima "(x or 'true') != 'false'": "no" valeva acceso.
    assert settings_registry.get_bool(db_session, "verify_before_execute") is False
    settings_repo.set_setting(db_session, "upload_screenshot_count", "garbage")
    assert settings_registry.get_int(db_session, "upload_screenshot_count") == 4


def test_the_api_refuses_an_invalid_value(client):
    response = client.put("/api/settings/confidence_threshold_auto_media_to_torrent", json={"value": "95"})
    assert response.status_code == 400 and response.json()["detail"]["code"] == "setting_invalid_value"
    assert client.put("/api/settings/verify_before_execute", json={"value": "on"}).json()["value"] == "true"
