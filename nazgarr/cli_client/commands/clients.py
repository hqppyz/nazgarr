"""nazgarr client: i client torrent (Configurazione › Client). Password e
token si chiedono a schermo, o da stdin con --password-stdin."""

import typer

from nazgarr.cli_client.context import api, state
from nazgarr.cli_client.helpers import find, secret
from nazgarr.cli_client.output import EXIT_USAGE, confirm, console, emit, err_console, fail, table

app = typer.Typer(help="Torrent clients: add, test, link to disks, default labels.", no_args_is_help=True)
TYPES = ("qbittorrent", "qui", "deluge", "transmission", "rutorrent")
# La Web UI di Deluge ha solo la password, nessun utente.
PASSWORD_ONLY = ("deluge",)


def _client(client, ref: str) -> dict:
    return find(client.get("/api/torrent-clients"), ref, "torrent client")


def _render(clients: list[dict], disks: dict[int, str]) -> None:
    table(["ID", "Client", "Type", "URL", "Enabled", "Disks", "Torrents", "Categories", "Tags"], [
        (c["id"], c["label"], c["adapter_type"] + (f" #{c['qui_instance_id']}" if c.get("qui_instance_id") else ""),
         c["base_url"], "yes" if c["enabled"] else "no",
         ", ".join(disks.get(a["disk_id"], f"#{a['disk_id']}") for a in c["disks"]) or "all",
         c.get("torrent_count", ""),
         " / ".join(x for x in (c.get("category_movie"), c.get("category_tv"), c.get("category_anime")) if x),
         " / ".join(x for x in (c.get("tags_upload"), c.get("tags_reseed")) if x))
        for c in clients])


@app.command("ls")
def list_clients(ctx: typer.Context):
    """The torrent clients."""
    client = api(ctx)
    disks = {d["id"]: d["label"] for d in client.get("/api/disks")}
    emit(state(ctx), client.get("/api/torrent-clients"), lambda data: _render(data, disks))


@app.command("add")
def add_client(
    ctx: typer.Context,
    label: str = typer.Argument(..., help="A name for the client, e.g. qbit."),
    url: str = typer.Option(..., "--url", help="Web UI address, e.g. http://qbittorrent:8080. rTorrent: its XML-RPC "
                            "URL (http://rtorrent:8000/RPC2) or the ruTorrent address."),
    adapter_type: str = typer.Option("qbittorrent", "--type",
                                     help="qbittorrent, qui, deluge, transmission or rutorrent (or a plugin type)."),
    username: str = typer.Option(None, "--username", "-u",
                                 help="Web UI user (the password is asked). Deluge: no user, its password is asked."),
    qui_instance: int = typer.Option(None, "--qui-instance", help="qui: the instance ID (the API token is asked)."),
    password_stdin: bool = typer.Option(False, "--password-stdin", help="Read the password or token from stdin."),
    test: bool = typer.Option(True, "--test/--no-test", help="Test the connection after adding it."),
):
    """Add a torrent client."""
    body = {"label": label, "adapter_type": adapter_type, "base_url": url}
    if adapter_type == "qui":
        if qui_instance is None:
            raise fail("qui needs --qui-instance.", EXIT_USAGE)
        body |= {"qui_instance_id": qui_instance, "api_token": secret("qui API token", password_stdin)}
    elif adapter_type in PASSWORD_ONLY:
        body |= {"password": secret("Password", password_stdin)}
    elif username:
        body |= {"username": username, "password": secret("Password", password_stdin)}
    client = api(ctx)
    created = client.post("/api/torrent-clients", body)
    emit(state(ctx), created, lambda c: console.print(f"Client [bold]{c['label']}[/bold] (#{c['id']}) added."))
    if test and not state(ctx).json:
        _print_test(client.post(f"/api/torrent-clients/{created['id']}/test"))


@app.command("edit")
def edit_client(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="Client name or ID."),
    label: str = typer.Option(None, "--label", help="New name."),
    url: str = typer.Option(None, "--url", help="New address."),
    username: str = typer.Option(None, "--username", "-u", help="New user."),
    new_password: bool = typer.Option(False, "--password", help="Ask a new password (or token, for qui)."),
    password_stdin: bool = typer.Option(False, "--password-stdin", help="Read it from stdin."),
    enabled: bool = typer.Option(None, "--enable/--disable", help="Turn the client on or off."),
    category_movie: str = typer.Option(None, "--category-movie", help="Default category for movies."),
    category_tv: str = typer.Option(None, "--category-tv", help="Default category for shows."),
    category_anime: str = typer.Option(None, "--category-anime", help="Default category for anime."),
    tags_upload: str = typer.Option(None, "--tags-upload", help="Tags for your uploads (comma separated)."),
    tags_reseed: str = typer.Option(None, "--tags-reseed", help="Tags for reseeds (comma separated)."),
):
    """Change a torrent client."""
    client = api(ctx)
    found = _client(client, ref)
    body = {k: v for k, v in {
        "label": label, "base_url": url, "username": username, "enabled": enabled,
        "category_movie": category_movie, "category_tv": category_tv, "category_anime": category_anime,
        "tags_upload": tags_upload, "tags_reseed": tags_reseed}.items() if v is not None}
    if new_password or password_stdin:
        key = "api_token" if found["adapter_type"] == "qui" else "password"
        body[key] = secret("New token" if key == "api_token" else "New password", password_stdin)
    if not body:
        raise fail("Nothing to change (see --help).", EXIT_USAGE)
    updated = client.patch(f"/api/torrent-clients/{found['id']}", body)
    emit(state(ctx), updated, lambda c: console.print(f"Client {c['label']} updated."))


@app.command("rm")
def remove_client(ctx: typer.Context, ref: str = typer.Argument(..., help="Client name or ID."),
                  yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation.")):
    """Remove a client from Nazgarr (its torrents are not touched)."""
    client = api(ctx)
    found = _client(client, ref)
    confirm(f"Remove client {found['label']} from Nazgarr? Its torrents are not touched.", yes)
    client.delete(f"/api/torrent-clients/{found['id']}")
    console.print(f"Client {found['label']} removed.")


def _print_test(result: dict) -> None:
    if result["status"] == "ok":
        console.print(f"[green]Connected:[/green] {result.get('torrents_found', 0)} torrents found.")
    else:
        err_console.print(f"[red]Connection failed:[/red] {result.get('error')}")


@app.command("test")
def test_client(ctx: typer.Context, ref: str = typer.Argument(..., help="Client name or ID.")):
    """Test the connection."""
    client = api(ctx)
    result = client.post(f"/api/torrent-clients/{_client(client, ref)['id']}/test")
    emit(state(ctx), result, _print_test)
    if result["status"] != "ok":
        raise typer.Exit(1)


@app.command("categories")
def categories(ctx: typer.Context, ref: str = typer.Argument(..., help="Client name or ID.")):
    """The categories defined in the client."""
    client = api(ctx)
    data = client.get(f"/api/torrent-clients/{_client(client, ref)['id']}/categories")
    emit(state(ctx), data, lambda d: console.print("\n".join(d.get("categories") or []) or "(none)"))


@app.command("link")
def link_disk(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="Client name or ID."),
    disk: str = typer.Argument(..., help="Disk name or ID."),
    client_root: str = typer.Option(None, "--client-root",
                                    help="How the client sees the folder below (or the whole disk), e.g. /download."),
    folder: str = typer.Option(None, "--folder",
                               help="The disk folder the client sees as --client-root (default: the whole disk)."),
):
    """Use the client for a disk, and say where the client sees it if not at the same path.

    E.g. Nazgarr /data/qbittorrent is qBittorrent /download:
    nazgarr client link qbit main --folder qbittorrent --client-root /download
    """
    if folder and not client_root:
        raise fail("--folder needs --client-root (how the client sees that folder).", EXIT_USAGE)
    client = api(ctx)
    found, target = _client(client, ref), find(client.get("/api/disks"), disk, "disk")
    body = {k: v for k, v in {"torrent_client_root_path": client_root, "local_rel_path": folder}.items() if v}
    client.post(f"/api/torrent-clients/{found['id']}/disks/{target['id']}", body)
    mapped = (f" ({target['root_path'].rstrip('/')}/{folder or ''}".rstrip("/") + f" = {client_root})"
              if client_root else "")
    console.print(f"Client {found['label']} linked to disk {target['label']}{mapped}.")


@app.command("unlink")
def unlink_disk(ctx: typer.Context, ref: str = typer.Argument(..., help="Client name or ID."),
                disk: str = typer.Argument(..., help="Disk name or ID.")):
    """Stop using the client for a disk."""
    client = api(ctx)
    found, target = _client(client, ref), find(client.get("/api/disks"), disk, "disk")
    client.delete(f"/api/torrent-clients/{found['id']}/disks/{target['id']}")
    console.print(f"Client {found['label']} unlinked from disk {target['label']}.")
