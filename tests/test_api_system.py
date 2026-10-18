import logging
import random
import re

import httpx

from nazgarr.api import system
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


def test_a_stored_result_that_does_not_say_when_makes_the_automatic_check_due(db_session, monkeypatch):
    """Un esito senza un checked_at leggibile (o che non è un oggetto, o con
    una data nel futuro) vale come nessun controllo: prima fromisoformat (o
    .get) sollevava a ogni giro e il controllo automatico non si rifaceva
    più (audit 2026-10-18)."""
    import json
    from datetime import UTC, datetime

    from nazgarr.core import settings_repo
    from nazgarr.core.version import __version__

    _fake_releases(monkeypatch, [{"tag_name": "v99.0.0", "prerelease": False}])
    settings_repo.set_setting(db_session, "update_check_auto", "true")
    now = datetime(2026, 10, 5, 12, tzinfo=UTC)
    for stored in (json.dumps({"current_version": __version__, "checked_at": "yesterday"}),
                   json.dumps({"current_version": __version__}),
                   json.dumps({"current_version": __version__, "checked_at": "2026-10-05T11:00:00"}),  # senza fuso
                   json.dumps({"current_version": __version__, "checked_at": 5}),
                   # nel futuro: l'orologio era avanti, poi è stato corretto
                   json.dumps({"current_version": __version__, "checked_at": "2026-12-01T00:00:00+00:00"}),
                   "[1]", '"x"'):
        settings_repo.set_setting(db_session, updates.LAST_CHECK_KEY, stored)
        assert updates.last_check(db_session) is None or isinstance(updates.last_check(db_session), dict)
        assert updates.check_if_due(db_session, now) is True, stored
        assert updates.last_check(db_session)["latest_version"] == "v99.0.0"


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


def _read_whole_file(path, min_level, limit=500):
    """La lettura di prima (tutto il file, dall'inizio): il riferimento per
    quella dalla fine."""
    order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    min_index = order.index(min_level) if min_level in order else 0
    entries = []
    for line in path.read_text(errors="replace").split("\n")[:-1]:
        match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\S+)\s+([^:]+): (.*)$", line)
        if match:
            entries.append(list(match.groups()))
        elif entries:
            entries[-1][3] += "\n" + line
    kept = [e for e in entries if e[1] in order and order.index(e[1]) >= min_index]
    return [tuple(e) for e in reversed(kept[-limit:])]


def _write_log(path, count, seed=7):
    rng = random.Random(seed)
    lines = ["orphan continuation before the first entry"]
    for i in range(count):
        level = rng.choice(["DEBUG", "INFO", "INFO", "WARNING", "ERROR", "NOTICE"])
        stamp = f"2026-10-18 10:{i // 60 % 60:02d}:{i % 60:02d}"
        lines.append(f"{stamp} {level:<8} nazgarr.test: message {i} è già fatto ✓")
        for k in range(rng.choice([0, 0, 0, 1, 3])):
            lines.append(f"  Traceback line {k} of {i} — ünïcode")
        if rng.random() < 0.05:
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_logs_read_from_the_end_match_the_whole_file(tmp_path):
    log = tmp_path / "nazgarr.log"
    _write_log(log, 3000)
    for level in ["DEBUG", "INFO", "ERROR", "BOGUS"]:
        for chunk in [64, 1000, 256 * 1024]:  # blocchi piccoli: righe e caratteri a cavallo
            entries = system.read_log_entries(log, level, chunk_bytes=chunk)
            got = [(e.timestamp, e.level, e.logger, e.message) for e in entries]
            assert got == _read_whole_file(log, level), (level, chunk)


def test_logs_without_a_final_newline_and_with_few_entries(tmp_path):
    log = tmp_path / "nazgarr.log"
    log.write_text(
        "2026-10-18 10:00:00 INFO     a: first\n  more\n2026-10-18 10:00:01 ERROR    b: second", encoding="utf-8")
    entries = system.read_log_entries(log, "INFO", chunk_bytes=8)
    assert [(e.logger, e.message) for e in entries] == [("b", "second"), ("a", "first\n  more")]


def test_logs_stop_reading_once_the_last_entries_are_found(tmp_path, monkeypatch):
    log = tmp_path / "nazgarr.log"
    _write_log(log, 20000)
    read = []
    real_open = type(log).open

    def counting_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        real_read = handle.read
        handle.read = lambda size=-1: read.append(size) or real_read(size)
        return handle

    monkeypatch.setattr(type(log), "open", counting_open)
    entries = system.read_log_entries(log, "DEBUG", chunk_bytes=64 * 1024)
    assert len(entries) == 500
    assert read and sum(read) < log.stat().st_size / 4


def test_a_malformed_stored_update_result_shows_no_banner(client):
    """Prima un 500 a ogni pagina: last_check controllava solo il JSON."""
    import json

    from nazgarr.core import settings_repo
    from nazgarr.core.version import __version__

    stored = [json.dumps({"current_version": __version__, "checked_at": "yesterday"}),
              "[1]", "5", '"x"']  # anche un valore che non è un oggetto JSON
    for value in stored:
        with client.app.state.session_factory() as session:
            settings_repo.set_setting(session, updates.LAST_CHECK_KEY, value)
        response = client.get("/api/system/update-status")
        assert response.status_code == 200 and response.json() is None, value


def test_old_log_lines_are_redacted_when_read(client, tmp_path):
    """Le righe scritte prima degli schemi nuovi restano nel file finché
    non ruota: la tab Logs le ripulisce in uscita (audit 2026-10-18)."""
    log = tmp_path / "nazgarr.log"
    log.write_text(
        "2026-10-18 10:00:00 INFO     httpx: HTTP Request: POST "
        "https://api.telegram.org/bot123456:AAH-SECRET/sendMessage\n"
        "2026-10-18 10:00:01 ERROR    nazgarr.x: failed https://u:pw@h/x\n"
        "  Traceback: https://discord.com/api/webhooks/42/HOOK-SECRET\n",
        encoding="utf-8")
    text = str([e.message for e in system.read_log_entries(log, "DEBUG")])
    assert "AAH-SECRET" not in text and "pw@" not in text and "HOOK-SECRET" not in text
    assert "/bot<redacted>/sendMessage" in text

    logging.getLogger("tests.system").error("failed https://u:pw@h/x /bot123456:AAH-SECRET/sendMessage")
    body = client.get("/api/system/logs", params={"min_level": "DEBUG"}).json()
    assert body["available"] and "AAH-SECRET" not in str(body) and "pw@" not in str(body)
