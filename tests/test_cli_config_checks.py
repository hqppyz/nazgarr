"""Il CLI e i controlli della configurazione (audit 2026-10-18): una
pianificazione salvata che non si legge, un indirizzo in chiaro verso un host
pubblico, cosa se ne va eliminando un tracker o un disco."""

from tests import test_cli_client
from tests.test_cli_client import _login, run

cli_env = test_cli_client.cli_env  # il fixture del CLI contro l'app in memoria


def test_schedule_show_says_a_stored_cron_cannot_be_read(cli_env, client, capsys):
    from nazgarr.core import settings_repo

    _login(capsys)
    with client.app.state.session_factory() as session:
        settings_repo.set_setting(session, "schedule_cron", "every night please")

    code, out, err = run(capsys, "schedule", "show")

    assert code == 0, err
    assert "cannot be read" in err and "every night please" in err
    assert "run on their own" not in out


def _recording(monkeypatch):
    """Le richieste GET del CLI, con i loro parametri."""
    from nazgarr.cli_client import http

    calls: list[tuple[str, dict]] = []
    original = http.Api.request

    def request(self, method, path, *, json_body=None, params=None):
        if method == "GET":
            calls.append((path, dict(params or {})))
        return original(self, method, path, json_body=json_body, params=params)

    monkeypatch.setattr(http.Api, "request", request)
    return calls


def test_runs_ls_asks_the_server_only_for_the_runs_it_shows(cli_env, client, capsys, monkeypatch):
    """Prima arrivavano tutte le run, e il CLI ne teneva 10 (audit 2026-10-18)."""
    import json
    from datetime import UTC, datetime

    from nazgarr.core.models import RunLog

    with client.app.state.session_factory() as session:
        for _ in range(5):
            session.add(RunLog(run_type="manual", started_at=datetime.now(UTC), finished_at=datetime.now(UTC)))
        session.commit()
    _login(capsys)
    calls = _recording(monkeypatch)

    code, out, err = run(capsys, "--json", "runs", "ls", "-n", "2")

    assert code == 0, err
    assert len(json.loads(out)) == 2
    assert ("/api/runs", {"limit": 2}) in calls


def test_status_reads_only_the_uploads_still_in_progress(cli_env, client, capsys, monkeypatch):
    _login(capsys)
    calls = _recording(monkeypatch)

    code, _out, err = run(capsys, "--json", "status")

    assert code == 0, err
    assert ("/api/uploads", {"scope": "active"}) in calls


def test_plain_http_to_a_public_host_is_saved_with_a_warning(cli_env, client, capsys, monkeypatch):
    """Decisione dell'utente, 2026-10-18: si salva, con un avviso; la LAN no."""
    import json
    import socket

    from nazgarr.api import types

    real = socket.getaddrinfo
    addresses = {"tracker.public.example": "93.184.216.34", "qbit.lan": "192.168.1.20"}
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: (
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addresses[host], 0))] if host in addresses
        else real(host, port, *a, **k)))
    types.forget_public_hosts()
    _login(capsys)

    code, out, err = run(capsys, "--json", "tracker", "add", "pub", "--url", "http://tracker.public.example",
                         "--token-stdin", "--no-profile", stdin="tok\n")
    assert code == 0, err
    assert json.loads(out)["insecure_public_url"] is True  # --json resta pulito, l'avviso va sullo stderr
    assert "Warning:" in err and "travel in clear" in err

    code, _out, err = run(capsys, "client", "add", "lan", "--url", "http://qbit.lan:8080", "--no-test")
    assert code == 0, err
    assert "Warning:" not in err
    types.forget_public_hosts()


def test_removing_a_used_tracker_or_disk_says_what_goes_and_asks_first(cli_env, client, capsys):
    """Decisione dell'utente, 2026-10-18: la storia va con loro, e il CLI dice
    quanta prima di chiedere --yes."""
    from nazgarr.core.models import SeedJob
    from tests.test_delete_used_tracker_and_disk import _used_tracker_and_disk

    _disk_id, _tracker_id = _used_tracker_and_disk(client)
    _login(capsys)

    code, out, err = run(capsys, "tracker", "rm", "ITT")
    out = " ".join(out.split())  # rich va a capo alla larghezza del terminale
    assert code == 3 and "--yes" in err  # niente terminale: senza --yes non si cancella
    assert "1 candidate, 1 review, 1 reseed record (1 still seeding" in out
    assert "Nothing changes on the tracker" in out

    code, out, err = run(capsys, "disk", "rm", "Disk 1")
    out = " ".join(out.split())
    assert code == 3
    assert "1 library file record, 1 seeding file record" in out and "No file on the disk is touched" in out

    with client.app.state.session_factory() as session:
        session.query(SeedJob).one().final_status = "in_progress"
        session.commit()
    code, _out, err = run(capsys, "tracker", "rm", "ITT", "--yes")
    assert code == 1 and "in progress" in err
    assert client.get("/api/trackers").json()  # rifiutato prima di chiedere, anche con --yes

    with client.app.state.session_factory() as session:
        session.query(SeedJob).one().final_status = "seeding"
        session.commit()
    code, out, err = run(capsys, "tracker", "rm", "ITT", "--yes")
    assert code == 0, err
    assert client.get("/api/trackers").json() == []
