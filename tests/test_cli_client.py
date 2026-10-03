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
