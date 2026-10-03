import io
import json
import stat
import sys

import pytest
from fastapi.testclient import TestClient

from nazgarr import cli
from nazgarr.cli_client import http, profiles

URL = "http://nazgarr.test"


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Il CLI contro l'app in memoria: niente rete, un cli.toml temporaneo."""
    from nazgarr.main import app

    monkeypatch.setenv("NAZGARR_CLI_CONFIG", str(tmp_path / "cli.toml"))
    for name in ("NAZGARR_URL", "NAZGARR_API_KEY", "NAZGARR_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(http, "CLIENT_FACTORY", lambda base_url, headers: TestClient(app, base_url=base_url,
                                                                                      headers=headers))
    return tmp_path


def run(capsys, *argv, stdin: str = ""):
    sys.stdin = io.StringIO(stdin)
    try:
        code = cli.main(list(argv))
    finally:
        sys.stdin = sys.__stdin__
    out = capsys.readouterr()
    return code, out.out, out.err


def test_setup_creates_the_account_and_keeps_only_an_api_key(cli_env, anon_client, capsys):
    from nazgarr.main import app

    code, out, err = run(capsys, "setup", "--url", URL, "--username", "admin", "--setup-code",
                         app.state.setup_code, "--password-stdin", stdin="supersecret1\n")

    assert code == 0, err
    default, saved = profiles.load()
    assert default == "default" and saved["default"].url == URL and saved["default"].api_key.startswith("nzg_")
    assert stat.S_IMODE((cli_env / "cli.toml").stat().st_mode) == 0o600
    assert "supersecret1" not in (cli_env / "cli.toml").read_text()

    code, out, _err = run(capsys, "--json", "status")
    assert code == 0 and json.loads(out)["setup"]["complete"] is False


def test_login_scan_and_the_raw_api(cli_env, client, capsys):
    code, _out, err = run(capsys, "login", "--url", URL, "-u", "admin", "--password-stdin", stdin="supersecret1\n")
    assert code == 0, err

    code, out, err = run(capsys, "--json", "scan", "--wait")
    assert code == 0, err
    scan = json.loads(out)
    assert scan["finished_at"] and scan["run_type"] == "bulk_import"

    code, out, _err = run(capsys, "--json", "runs", "ls")
    assert [r["id"] for r in json.loads(out)] == [scan["id"]]
    code, out, _err = run(capsys, "api", "GET", "/api/disks")
    assert code == 0 and json.loads(out) == []
    code, out, _err = run(capsys, "--json", "review", "ls")
    assert json.loads(out) == []


def test_a_read_only_key_cannot_change_anything(cli_env, client, capsys):
    run(capsys, "login", "--url", URL, "-u", "admin", "--read-only", "--password-stdin", stdin="supersecret1\n")

    code, _out, err = run(capsys, "scan")

    assert code == 4 and "read" in err.lower()


def test_actions_that_touch_files_ask_first(cli_env, client, capsys):
    run(capsys, "login", "--url", URL, "-u", "admin", "--password-stdin", stdin="supersecret1\n")

    code, _out, err = run(capsys, "review", "approve", "1")  # niente terminale, niente --yes

    assert code == 3 and "--yes" in err


def test_errors_are_explained(cli_env, client, capsys):
    code, _out, err = run(capsys, "status")
    assert code == 4 and "nazgarr login" in err

    run(capsys, "login", "--url", URL, "-u", "admin", "--password-stdin", stdin="supersecret1\n")
    code, _out, err = run(capsys, "api", "POST", "/api/disks", "-d", '{"label": "x", "root_path": "/nowhere"}')
    assert code == 1 and "Error:" in err

    code, _out, err = run(capsys, "login", "--url", URL, "-u", "admin", "--password-stdin", stdin="wrong\n")
    assert code == 4


def test_logout_forgets_the_profile(cli_env, client, capsys):
    run(capsys, "login", "--url", URL, "-u", "admin", "--password-stdin", stdin="supersecret1\n")
    code, _out, _err = run(capsys, "logout")
    assert code == 0 and profiles.load()[1] == {}


def test_profiles_and_environment(cli_env, client, capsys, monkeypatch):
    run(capsys, "--profile", "home", "login", "--url", URL, "-u", "admin", "--password-stdin",
        stdin="supersecret1\n")
    run(capsys, "--profile", "box", "login", "--url", URL, "-u", "admin", "--password-stdin",
        stdin="supersecret1\n")
    code, out, _err = run(capsys, "--json", "profile", "ls")
    assert sorted(p["name"] for p in json.loads(out)) == ["box", "home"]
    run(capsys, "profile", "use", "box")
    assert profiles.load()[0] == "box"

    monkeypatch.setenv("NAZGARR_API_KEY", "nzg_wrong")
    code, _out, _err = run(capsys, "status")
    assert code == 4  # la variabile d'ambiente vince sul file


def test_the_cli_messages_match_the_web_ui():
    from scripts.export_cli_messages import messages

    assert json.loads((http.resources.files("nazgarr.cli_client") / "messages_en.json").read_text()) == messages()


# --- fase 2: configurazione -----------------------------------------------------


def _login(capsys):
    code, _out, err = run(capsys, "login", "--url", URL, "-u", "admin", "--password-stdin", stdin="supersecret1\n")
    assert code == 0, err


def _configure(capsys, root):
    for folder in ("torrents", "media/movies", "media/tv"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    steps = [
        (("disk", "add", "main", str(root)), ""),
        (("disk", "folder", "add", "main", "seeding", "torrents"), ""),
        (("disk", "folder", "add", "main", "media", "media/movies"), ""),
        (("client", "add", "qbit", "--url", "http://qbit.test:8080", "-u", "admin", "--password-stdin",
          "--no-test"), "qbitpass\n"),
        (("client", "link", "qbit", "main"), ""),
        (("client", "edit", "qbit", "--tags-upload", "release"), ""),
        (("tracker", "add", "--preset", "itt", "--token-stdin", "--client", "qbit", "--min-seed-time", "7d"),
         "tracker-token\n"),
        (("tracker", "profile", "set", "itt", "--internal", "--category", "movie=9"), ""),
        (("settings", "set", "upload_screenshot_count", "6"), ""),
        (("schedule", "set", "0 */6 * * *"), ""),
    ]
    for argv, stdin in steps:
        code, _out, err = run(capsys, *argv, stdin=stdin)
        assert code == 0, (argv, err)


def test_the_whole_setup_from_the_command_line(cli_env, client, capsys):
    _login(capsys)
    root = client.scan_root / "data"
    _configure(capsys, root)

    disk = json.loads(run(capsys, "--json", "disk", "ls")[1])[0]
    assert (disk["seeding_folders"], disk["media_folders"]) == (["torrents"], ["media/movies"])
    qbit = json.loads(run(capsys, "--json", "client", "ls")[1])[0]
    assert qbit["disks"][0]["disk_id"] == disk["id"] and qbit["tags_upload"] == "release"
    tracker = json.loads(run(capsys, "--json", "tracker", "ls")[1])[0]
    assert (tracker["label"], tracker["torrent_client_id"], tracker["min_seed_time_seconds"]) == (
        "ITT (ItaTorrents)", qbit["id"], 7 * 86400)
    profile = json.loads(run(capsys, "--json", "tracker", "profile", "show", "ITT (ItaTorrents)")[1])
    assert profile["default_internal"] is True and profile["category_id_map"]["movie"] == 9
    assert run(capsys, "settings", "get", "upload_screenshot_count")[1].strip() == "6"

    # Un nome sbagliato: elenca quelli che ci sono.
    code, _out, err = run(capsys, "disk", "test", "nope")
    assert code == 2 and "main" in err
    # Una cartella che si sovrappone: il motivo del server.
    code, _out, err = run(capsys, "disk", "folder", "add", "main", "media", "torrents")
    assert code == 1 and "overlaps" in err


def test_safety_settings_ask_before_changing(cli_env, client, capsys):
    _login(capsys)
    code, _out, err = run(capsys, "settings", "set", "verify_before_execute", "false")
    assert code == 3 and "--yes" in err
    code, _out, err = run(capsys, "settings", "set", "tmdb_api_key", "abc")
    assert code == 2 and "never passed as arguments" in err


def test_config_export_and_import(cli_env, client, capsys, monkeypatch):
    import yaml

    _login(capsys)
    root = client.scan_root / "data"
    _configure(capsys, root)

    code, out, _err = run(capsys, "config", "export")
    assert code == 0
    exported = yaml.safe_load(out)
    assert exported["torrent_clients"][0]["password"] == "${NAZGARR_CLIENT_QBIT_PASSWORD}"
    assert "tracker-token" not in out and "qbitpass" not in out
    assert exported["settings"]["upload_screenshot_count"] == "6" and exported["schedule"] == "0 */6 * * *"

    file = cli_env / "nazgarr.yaml"
    file.write_text(out)
    code, out, _err = run(capsys, "config", "import", str(file))
    assert code == 0 and "Nothing to change" in out

    # Una cartella in più, un tag cambiato, un tracker nuovo con il token dall'ambiente.
    exported["disks"][0]["media_folders"].append("media/tv")
    exported["torrent_clients"][0]["tags"]["upload"] = "mine"
    exported["trackers"].append({"label": "Other", "type": "unit3d", "url": "https://other.example",
                                 "api_token": "${OTHER_TOKEN}", "client": "qbit"})
    file.write_text(yaml.safe_dump(exported))
    monkeypatch.setenv("OTHER_TOKEN", "secret-token")

    code, out, _err = run(capsys, "config", "import", str(file), "--dry-run")
    assert code == 0 and "+ media folder main:media/tv" in out and "+ tracker Other" in out
    assert json.loads(run(capsys, "--json", "disk", "ls")[1])[0]["media_folders"] == ["media/movies"]  # dry run

    code, out, err = run(capsys, "config", "import", str(file), "--yes")
    assert code == 0, err
    assert json.loads(run(capsys, "--json", "disk", "ls")[1])[0]["media_folders"] == ["media/movies", "media/tv"]
    assert json.loads(run(capsys, "--json", "client", "ls")[1])[0]["tags_upload"] == "mine"
    assert [t["label"] for t in json.loads(run(capsys, "--json", "tracker", "ls")[1])] == [
        "ITT (ItaTorrents)", "Other"]
    # Mai togliere: un client che il file non nomina resta.
    exported["torrent_clients"] = []
    file.write_text(yaml.safe_dump(exported))
    run(capsys, "config", "import", str(file), "--yes")
    assert len(json.loads(run(capsys, "--json", "client", "ls")[1])) == 1
