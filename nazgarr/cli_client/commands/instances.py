"""nazgarr instance: le altre istanze che la web UI di questa può aprire
(nazgarr/instances.py). Il registro vuole il login (una API key non usa le
chiavi delle altre istanze): questi comandi chiedono la password."""

import typer

from nazgarr.cli_client.context import state
from nazgarr.cli_client.helpers import find, login_api, secret
from nazgarr.cli_client.output import confirm, console, emit, table

app = typer.Typer(help="Other instances this one's web UI can open (needs your password).", no_args_is_help=True)


def _status(i: dict) -> str:
    s = i.get("status") or {}
    if not s:
        return ""
    return " · ".join(x for x in (s.get("status"), s.get("version"), s.get("level"), s.get("compatibility")) if x)


@app.command("ls")
def list_instances(ctx: typer.Context):
    """The registered instances, with their status."""
    data = login_api(ctx).get("/api/instances", probe="true")
    emit(state(ctx), data, lambda d: table(["ID", "Name", "Address", "Status"],
                                           [(i["id"], i["label"], i["base_url"], _status(i)) for i in d["instances"]]))


@app.command("add")
def add_instance(
    ctx: typer.Context,
    label: str = typer.Argument(..., help="A name, e.g. seedbox."),
    url: str = typer.Option(..., "--url", help="Its address (https:// if public)."),
    key_stdin: bool = typer.Option(False, "--key-stdin", help="Read its API key from stdin."),
):
    """Register an instance with one of its API keys (asked)."""
    key = secret("Its API key", key_stdin)
    created = login_api(ctx).post("/api/instances", {"label": label, "base_url": url, "api_key": key})
    emit(state(ctx), created, lambda i: console.print(f"Instance {i['label']} added: {_status(i)}"))


@app.command("test")
def test_instance(ctx: typer.Context, ref: str = typer.Argument(..., help="Name or ID.")):
    """Test the connection to an instance."""
    client = login_api(ctx)
    found = find(client.get("/api/instances")["instances"], ref, "instance")
    result = client.post(f"/api/instances/{found['id']}/test")
    emit(state(ctx), result, lambda i: console.print(f"{i['label']}: {_status(i)}"))


@app.command("rm")
def remove_instance(ctx: typer.Context, ref: str = typer.Argument(..., help="Name or ID."),
                    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation.")):
    """Remove an instance (nothing changes on it)."""
    client = login_api(ctx)
    found = find(client.get("/api/instances")["instances"], ref, "instance")
    confirm(f"Remove instance {found['label']}?", yes)
    client.delete(f"/api/instances/{found['id']}")
    console.print(f"Instance {found['label']} removed.")
