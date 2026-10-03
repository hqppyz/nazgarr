"""nazgarr settings, nazgarr schedule e nazgarr arr: le impostazioni della
web UI, la pianificazione delle scansioni e Radarr/Sonarr."""

import sys
from pathlib import Path

import typer

from nazgarr.cli_client import settings_catalog as catalog
from nazgarr.cli_client.context import api, state
from nazgarr.cli_client.helpers import find, login_api, secret
from nazgarr.cli_client.http import ApiError
from nazgarr.cli_client.output import EXIT_USAGE, confirm, console, emit, err_console, fail, table

app = typer.Typer(help="Every setting of the web UI.", no_args_is_help=True)
schedule_app = typer.Typer(help="When scans run on their own.", no_args_is_help=True)
arr_app = typer.Typer(help="Radarr and Sonarr instances (optional).", no_args_is_help=True)


def _value_for_display(value: str | None, entry) -> str:
    if value is None or value == "":
        return "(not set)"
    if entry is not None and entry.kind == "secret":
        return "(set)"
    return value if len(value) < 70 else value[:67] + "…"


@app.command("ls")
def list_settings(ctx: typer.Context):
    """The known settings with their current values (secrets only as set / not set)."""
    client = api(ctx)
    rows = []
    for entry in catalog.CATALOG:
        if entry.kind == "secret":
            value = "(needs login to read)"
        else:
            try:
                value = client.get(f"/api/settings/{entry.key}").get("value")
            except ApiError as exc:
                value = f"({exc.code})"
        rows.append({"key": entry.key, "value": value, "help": entry.help, "safety": entry.safety})
    emit(state(ctx), rows, lambda data: table(
        ["Key", "Value", "Meaning"],
        [(r["key"] + (" [safety]" if r["safety"] else ""), _value_for_display(r["value"], catalog.BY_KEY[r["key"]]),
          r["help"]) for r in data]))


@app.command("get")
def get_setting(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="The setting key (see `nazgarr settings ls`)."),
    password_stdin: bool = typer.Option(False, "--password-stdin", help="For secrets: read your password from stdin."),
):
    """Print one setting (secrets need your password)."""
    client = login_api(ctx, password_stdin) if catalog.needs_login(key, writing=False) else api(ctx)
    data = client.get(f"/api/settings/{key}")
    emit(state(ctx), data, lambda d: typer.echo(d.get("value") if d.get("value") is not None else ""))


@app.command("set")
def set_setting(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="The setting key (see `nazgarr settings ls`)."),
    value: str = typer.Argument(None, help="The new value (secrets are asked, never passed here)."),
    from_file: Path = typer.Option(None, "--file", help="Read the value from a file ('-' = stdin)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation (safety settings)."),
):
    """Change one setting. Secrets and safety settings ask for your password."""
    entry = catalog.BY_KEY.get(key)
    is_secret = (entry is not None and entry.kind == "secret") or any(w in key for w in catalog.SECRET_WORDS)
    if is_secret:
        if value is not None:
            raise fail("Secrets are never passed as arguments: run it without the value, it is asked.", EXIT_USAGE)
        value = secret(f"New value of {key}")
    elif from_file is not None:
        value = sys.stdin.read() if str(from_file) == "-" else from_file.read_text()
    if value is None:
        raise fail("Pass the value (or --file).", EXIT_USAGE)
    try:
        value = catalog.normalize(key, value)
    except ValueError as exc:
        raise fail(str(exc), EXIT_USAGE) from exc
    if entry is not None and entry.safety:
        confirm(f"{key} is a safety setting ({entry.help}) Change it to {value}?", yes)
    if entry is None:
        err_console.print(f"[yellow]Note:[/yellow] {key} is not a known setting; it is saved anyway.")
    client = login_api(ctx) if catalog.needs_login(key, writing=True) else api(ctx)
    client.put(f"/api/settings/{key}", {"value": value})
    console.print(f"{key} saved.")


# --- pianificazione -----------------------------------------------------------


@schedule_app.command("show")
def show_schedule(ctx: typer.Context):
    """The current schedule."""
    data = api(ctx).get("/api/schedule")
    emit(state(ctx), data, lambda d: console.print(f"Scans run on their own: {d['cron']}" if d["enabled"]
                                                   else "Scans run only when you start them."))


@schedule_app.command("set")
def set_schedule(ctx: typer.Context, cron: str = typer.Argument(
        ..., help="Standard 5-field cron, e.g. '0 */6 * * *' (every 6 hours), or 'off'.")):
    """Run scans on their own, or turn that off."""
    data = api(ctx).put("/api/schedule", {"cron": None if cron.lower() == "off" else cron})
    emit(state(ctx), data, lambda d: console.print(f"Schedule: {d['cron']}" if d["enabled"] else "Schedule off."))


# --- Radarr / Sonarr -----------------------------------------------------------

KINDS = ("radarr", "sonarr")


def _instances(client) -> list[dict]:
    return [{**i, "kind": kind} for kind in KINDS for i in client.get(f"/api/{kind}-instances")]


def _instance(client, kind: str, ref: str) -> dict:
    if kind not in KINDS:
        raise fail("The kind is radarr or sonarr.", EXIT_USAGE)
    return find(client.get(f"/api/{kind}-instances"), ref, f"{kind} instance")


@arr_app.command("ls")
def list_arr(ctx: typer.Context):
    """The Radarr and Sonarr instances."""
    emit(state(ctx), _instances(api(ctx)), lambda data: table(
        ["Kind", "ID", "Name", "URL", "Enabled", "Priority"],
        [(i["kind"], i["id"], i["label"], i["base_url"], "yes" if i["enabled"] else "no", i["priority"])
         for i in data]))


@arr_app.command("add")
def add_arr(
    ctx: typer.Context,
    kind: str = typer.Argument(..., help="radarr or sonarr."),
    label: str = typer.Argument(..., help="A name, e.g. radarr."),
    url: str = typer.Option(..., "--url", help="Address, e.g. http://radarr:7878."),
    key_stdin: bool = typer.Option(False, "--key-stdin", help="Read the API key from stdin."),
    priority: int = typer.Option(None, "--priority", help="Order among instances of the same kind."),
):
    """Add a Radarr or Sonarr instance (the API key is asked: Settings › General)."""
    if kind not in KINDS:
        raise fail("The kind is radarr or sonarr.", EXIT_USAGE)
    body = {"label": label, "base_url": url, "api_key": secret("API key", key_stdin)}
    if priority is not None:
        body["priority"] = priority
    client = api(ctx)
    created = client.post(f"/api/{kind}-instances", body)
    emit(state(ctx), created, lambda i: console.print(f"{kind.capitalize()} {i['label']} (#{i['id']}) added."))
    if not state(ctx).json:
        _print_test(client.post(f"/api/{kind}-instances/{created['id']}/test"))


def _print_test(result: dict) -> None:
    if result.get("status") == "ok":
        console.print(f"[green]Connected[/green] (version {result.get('version')}).")
    else:
        err_console.print(f"[red]Connection failed:[/red] {result.get('error')}")


@arr_app.command("test")
def test_arr(ctx: typer.Context, kind: str = typer.Argument(..., help="radarr or sonarr."),
             ref: str = typer.Argument(..., help="Name or ID.")):
    """Test the connection."""
    client = api(ctx)
    result = client.post(f"/api/{kind}-instances/{_instance(client, kind, ref)['id']}/test")
    emit(state(ctx), result, _print_test)


@arr_app.command("rm")
def remove_arr(ctx: typer.Context, kind: str = typer.Argument(..., help="radarr or sonarr."),
               ref: str = typer.Argument(..., help="Name or ID."),
               yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation.")):
    """Remove a Radarr or Sonarr instance from Nazgarr."""
    client = api(ctx)
    found = _instance(client, kind, ref)
    confirm(f"Remove {kind} {found['label']}?", yes)
    client.delete(f"/api/{kind}-instances/{found['id']}")
    console.print(f"{kind.capitalize()} {found['label']} removed.")
