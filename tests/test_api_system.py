import logging

import httpx

import nazgarr.api.system as system_module


def test_app_info(client):
    response = client.get("/api/system/info")
    assert response.status_code == 200
    body = response.json()
    assert body["version"]
    assert body["python_version"]
    assert "/" in body["platform"]
    assert body["started_at"]


def _fake_releases(monkeypatch, releases, status=200):
    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        return httpx.Response(status, json=releases, request=httpx.Request("GET", url))

    monkeypatch.setattr(system_module.httpx, "get", fake_get)


def test_update_check_no_releases_yet(client, monkeypatch):
    _fake_releases(monkeypatch, [])

    body = client.get("/api/system/update-check").json()
    assert body["update_available"] is False
    assert body["latest_version"] is None
    assert "No releases" in body["note"]


def test_update_check_available(client, monkeypatch):
    _fake_releases(monkeypatch, [{"tag_name": "v99.0.0", "prerelease": False}])

    body = client.get("/api/system/update-check").json()
    assert body["update_available"] is True
    assert body["latest_version"] == "v99.0.0"


RELEASES = [
    {"tag_name": "v0.3.4", "prerelease": True},
    {"tag_name": "v0.3.3", "prerelease": True},
    {"tag_name": "v0.3.0", "prerelease": False},
    {"tag_name": "v0.2.16", "prerelease": False},
]


def test_on_a_stable_version_only_newer_stable_releases_count():
    assert system_module._channel_and_latest(RELEASES, "0.3.0") == ("stable", "v0.3.0")
    assert system_module._channel_and_latest(RELEASES, "0.2.16") == ("stable", "v0.3.0")


def test_on_a_test_build_every_newer_build_counts():
    assert system_module._channel_and_latest(RELEASES, "0.3.3") == ("test", "v0.3.4")
    assert system_module._channel_and_latest(RELEASES, "0.3.0-dev") == ("test", "v0.3.4")


def test_logs_filters_by_level(client):
    logging.getLogger("tests.system").info("an info line")
    logging.getLogger("tests.system").error("an error line")

    all_logs = client.get("/api/system/logs", params={"min_level": "DEBUG"}).json()
    assert all_logs["available"] is True
    messages = [e["message"] for e in all_logs["entries"]]
    assert "an info line" in messages
    assert "an error line" in messages

    errors_only = client.get("/api/system/logs", params={"min_level": "ERROR"}).json()
    messages = [e["message"] for e in errors_only["entries"]]
    assert "an info line" not in messages
    assert "an error line" in messages
