import logging

import httpx

from nazgarr.core import updates


def test_app_info(client):
    response = client.get("/api/system/info")
    assert response.status_code == 200
    body = response.json()
    assert body["version"]
    assert body["python_version"]
    assert "/" in body["platform"]
    assert body["started_at"]


def _fake_releases(monkeypatch, releases, status=200, notes=None):
    """GitHub finto: l'elenco delle release e, al tag della nuova, il suo
    nazgarr/release_notes.json."""
    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        if "raw.githubusercontent.com" in url:
            if notes is None:
                return httpx.Response(404, request=httpx.Request("GET", url))
            return httpx.Response(200, json={"entries": notes}, request=httpx.Request("GET", url))
        return httpx.Response(status, json=releases, request=httpx.Request("GET", url))

    monkeypatch.setattr(updates.httpx, "get", fake_get)


def test_update_check_no_releases_yet(client, monkeypatch):
    _fake_releases(monkeypatch, [])

    body = client.get("/api/system/update-check").json()
    assert body["update_available"] is False
    assert body["latest_version"] is None
    assert "No releases" in body["note"]


def test_update_check_available_shows_the_notes_of_the_newer_versions(client, monkeypatch):
    notes = [
        {"version": "99.0.0", "highlights": {"it": ["Nuovo"], "en": ["New"]},
         "breaking": {"it": ["Cambia la porta"], "en": ["The port changes"]}},
        {"version": "0.0.1", "highlights": {"en": ["Old"]}},
    ]
    _fake_releases(monkeypatch, [{"tag_name": "v99.0.0", "prerelease": False}], notes=notes)

    body = client.get("/api/system/update-check").json()
    assert body["update_available"] is True
    assert body["latest_version"] == "v99.0.0"
    # Solo le versioni dopo quella in uso: la 0.0.1 è già passata.
    assert [n["version"] for n in body["notes"]] == ["99.0.0"]
    assert body["notes"][0]["breaking"]["en"] == ["The port changes"]
    # L'esito resta, per l'avviso nella barra laterale senza richiamare GitHub.
    assert client.get("/api/system/update-status").json()["latest_version"] == "v99.0.0"


def test_the_automatic_check_runs_only_when_turned_on_and_due(db_session, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from nazgarr.core import settings_repo

    _fake_releases(monkeypatch, [{"tag_name": "v99.0.0", "prerelease": False}])
    now = datetime(2026, 10, 5, 12, tzinfo=UTC)
    assert updates.check_if_due(db_session, now) is False  # spento di default
    settings_repo.set_setting(db_session, "update_check_auto", "true")
    assert updates.check_if_due(db_session, now) is True
    assert updates.check_if_due(db_session, now + timedelta(hours=1)) is False
    assert updates.check_if_due(db_session, now + timedelta(hours=13)) is True


def test_release_notes_are_shown_once_after_an_update(db_session, monkeypatch, tmp_path):
    import json

    from nazgarr.core import settings_repo

    notes = tmp_path / "release_notes.json"
    notes.write_text(json.dumps({"entries": [
        {"version": "0.9.0", "highlights": {"en": ["B"]}}, {"version": "0.8.5", "highlights": {"en": ["A"]}},
        {"version": "0.8.0", "highlights": {"en": ["old"]}},
    ]}))
    monkeypatch.setattr(updates, "NOTES_FILE", notes)
    monkeypatch.setattr(updates, "__version__", "0.9.0")

    updates.init_seen(db_session)  # installazione nuova: niente note arretrate
    assert updates.unseen_notes(db_session) == []
    settings_repo.set_setting(db_session, "release_notes_seen", "0.8.1")  # aggiornato dalla 0.8.1
    assert [n["version"] for n in updates.unseen_notes(db_session)] == ["0.9.0", "0.8.5"]
    updates.mark_seen(db_session)
    assert updates.unseen_notes(db_session) == []


RELEASES = [
    {"tag_name": "v0.3.4", "prerelease": True},
    {"tag_name": "v0.3.3", "prerelease": True},
    {"tag_name": "v0.3.0", "prerelease": False},
    {"tag_name": "v0.2.16", "prerelease": False},
]


def test_on_a_stable_version_only_newer_stable_releases_count():
    assert updates.channel_and_latest(RELEASES, "0.3.0") == ("stable", "v0.3.0")
    assert updates.channel_and_latest(RELEASES, "0.2.16") == ("stable", "v0.3.0")


def test_on_a_test_build_every_newer_build_counts():
    assert updates.channel_and_latest(RELEASES, "0.3.3") == ("test", "v0.3.4")
    assert updates.channel_and_latest(RELEASES, "0.3.0-dev") == ("test", "v0.3.4")


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
