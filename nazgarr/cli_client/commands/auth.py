"""setup, login, logout e i profili: come il CLI ottiene la sua API key.

Una API key non può crearne altre (nazgarr/auth.py require_login): login e
setup usano il token del login una volta sola, per creare la chiave che il
CLI salva in cli.toml. Le password si chiedono sempre a schermo (o da stdin
con --password-stdin), mai come argomento: finirebbero nella cronologia
della shell e in ps."""

import socket
import sys

import typer

from nazgarr.cli_client import profiles
from nazgarr.cli_client.context import state
from nazgarr.cli_client.http import Api
from nazgarr.cli_client.output import EXIT_USAGE, console, emit, err_console, fail, table

app = typer.Typer(help="Manage the saved Nazgarr instances (profiles).", no_args_is_help=True)


def _password(stdin: bool, confirm: bool = False) -> str:
    if stdin:
        return sys.stdin.readline().rstrip("\n")
    return typer.prompt("Password", hide_input=True, confirmation_prompt=confirm)


def _key_name(name: str | None) -> str:
    return name or f"cli-{socket.gethostname().split('.')[0]}"


def _save(name: str, url: str, created: dict) -> None:
    default, saved = profiles.load()
    saved[name] = profiles.Profile(name=name, url=url, api_key=created["key"], key_id=created["id"])
    if not saved or len(saved) == 1:
        default = name
    path = profiles.save(default, saved)
    console.print(f"Logged in to [bold]{url}[/bold] as profile [bold]{name}[/bold] "
                  f"(API key [bold]{created['name']}[/bold], saved in {path}).")


def setup(
    ctx: typer.Context,
    url: str = typer.Option(..., "--url", help="Address of the instance, e.g. http://nas:8080."),
    username: str = typer.Option(None, "--username", "-u", help="The account name (asked if missing)."),
    setup_code: str = typer.Option(None, "--setup-code", help="The one-time code from the log (asked if missing)."),
    password_stdin: bool = typer.Option(False, "--password-stdin", help="Read the password from stdin."),
    key_name: str = typer.Option(None, "--key-name", help="Name of the API key to create (default cli-HOSTNAME)."),
):
    """Create the account of a fresh installation, then log in.

    The one-time setup code is printed in the log at the first start
    (docker logs nazgarr, or the service log).
    """
    profile = state(ctx).profile or profiles.DEFAULT_PROFILE
    username = username or typer.prompt("Username")
    setup_code = setup_code or typer.prompt("Setup code (from the log)")
    password = _password(password_stdin, confirm=True)
    token = Api(url).post("/api/auth/setup", {"username": username, "password": password,
                                                "setup_code": setup_code})["access_token"]
    created = Api(url, token=token).post("/api/api-keys", {"name": _key_name(key_name), "level": "write"})
    _save(profile, url, created)


def login(
    ctx: typer.Context,
    url: str = typer.Option(None, "--url", help="Address of the instance, e.g. http://nas:8080."),
    username: str = typer.Option(None, "--username", "-u", help="The account name (asked if missing)."),
    password_stdin: bool = typer.Option(False, "--password-stdin", help="Read the password from stdin."),
    key_name: str = typer.Option(None, "--key-name", help="Name of the API key to create (default cli-HOSTNAME)."),
    read_only: bool = typer.Option(False, "--read-only", help="Create a read-only key (no changes possible)."),
):
    """Log in and save an API key for this computer.

    The password is used once, to create a dedicated API key; the CLI keeps
    only the key, in a file readable by you alone.
    """
    current = state(ctx)
    name = current.profile or profiles.DEFAULT_PROFILE
    url = url or current.url or (profiles.resolve(name, None) or profiles.Profile(name, "")).url
    if not url:
        raise fail("Which instance? Pass --url http://HOST:8080", EXIT_USAGE)
    username = username or typer.prompt("Username")
    token = Api(url).post("/api/auth/login", {"username": username,
                                                "password": _password(password_stdin)})["access_token"]
    created = Api(url, token=token).post(
        "/api/api-keys", {"name": _key_name(key_name), "level": "read" if read_only else "write"})
    _save(name, url, created)


def logout(
    ctx: typer.Context,
    revoke: bool = typer.Option(False, "--revoke", help="Also revoke the API key on the server (asks the password)."),
    username: str = typer.Option(None, "--username", "-u", help="The account name, with --revoke."),
    password_stdin: bool = typer.Option(False, "--password-stdin", help="Read the password from stdin."),
):
    """Forget the saved API key of the profile (and revoke it with --revoke)."""
    default, saved = profiles.load()
    name = state(ctx).profile or default
    profile = saved.get(name)
    if profile is None:
        raise fail(f"No saved profile named {name!r}.", EXIT_USAGE)
    if revoke and profile.key_id is not None:
        # Revocare una chiave vuole il login, non un'altra chiave.
        token = Api(profile.url).post("/api/auth/login", {
            "username": username or typer.prompt("Username"), "password": _password(password_stdin),
        })["access_token"]
        Api(profile.url, token=token).post(f"/api/api-keys/{profile.key_id}/revoke")
    del saved[name]
    if default == name:
        default = next(iter(saved), profiles.DEFAULT_PROFILE)
    profiles.save(default, saved)
    console.print(f"Profile [bold]{name}[/bold] removed" + (" and its API key revoked." if revoke else "."))
    if not revoke:
        err_console.print("The API key still works on the server: revoke it in Settings › API keys, "
                          "or run logout --revoke next time.")


@app.command("ls")
def list_profiles(ctx: typer.Context):
    """The saved instances."""
    default, saved = profiles.load()
    rows = [{"name": p.name, "url": p.url, "default": p.name == default, "key_id": p.key_id} for p in saved.values()]
    emit(state(ctx), rows, lambda data: table(
        ["", "Profile", "URL"], [("*" if r["default"] else "", r["name"], r["url"]) for r in data]))


@app.command("use")
def use_profile(name: str = typer.Argument(..., help="The profile to use by default.")):
    """Make a saved profile the default one."""
    _default, saved = profiles.load()
    if name not in saved:
        raise fail(f"No saved profile named {name!r}.", EXIT_USAGE)
    profiles.save(name, saved)
    console.print(f"Default profile: [bold]{name}[/bold].")
