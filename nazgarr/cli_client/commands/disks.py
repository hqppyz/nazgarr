"""nazgarr disk: i dischi e le loro cartelle (Configurazione › Storage)."""

import typer

from nazgarr.cli_client.context import api, state
from nazgarr.cli_client.helpers import find
from nazgarr.cli_client.output import EXIT_USAGE, confirm, console, emit, err_console, fail, size, table

app = typer.Typer(help="Disks and their media and seeding folders.", no_args_is_help=True)
folder_app = typer.Typer(help="The media and seeding folders of a disk.", no_args_is_help=True)
app.add_typer(folder_app, name="folder")

KINDS = ("media", "seeding")


def _disk(client, ref: str) -> dict:
    return find(client.get("/api/disks"), ref, "disk")


def _render_disks(disks: list[dict]) -> None:
    table(["ID", "Disk", "Root", "Seeding folders", "Media folders", "New hardlinks", "Uploads", "Watched"], [
        (d["id"], d["label"], d["root_path"], ", ".join(d.get("seeding_folders") or []) or "-",
         ", ".join(d.get("media_folders") or []) or "-", d.get("new_torrent_rel_path") or "(first seeding)",
         d.get("upload_rel_path") or "(first seeding)", d.get("watch_rel_path") or "-")
        for d in disks])


@app.command("ls")
def list_disks(ctx: typer.Context):
    """The disks with all their folders."""
    emit(state(ctx), api(ctx).get("/api/disks"), _render_disks)


@app.command("mounts")
def mounts(ctx: typer.Context):
    """Folders under disk_scan_root not added as a disk yet."""
    data = api(ctx).get("/api/disks/available-mounts")
    emit(state(ctx), data, lambda d: console.print(
        f"Scan root: {d['scan_root']}\n" + ("\n".join(f"  {m}" for m in d["mounts"]) or "  (none left)")))


@app.command("add")
def add_disk(
    ctx: typer.Context,
    label: str = typer.Argument(..., help="A name for the disk, e.g. main."),
    root_path: str = typer.Argument(..., help="Where it is mounted, e.g. /data (see `nazgarr disk mounts`)."),
):
    """Add a disk. Then add its folders with `nazgarr disk folder add`."""
    disk = api(ctx).post("/api/disks", {"label": label, "root_path": root_path})
    emit(state(ctx), disk, lambda d: console.print(f"Disk [bold]{d['label']}[/bold] (#{d['id']}) added."))


@app.command("set")
def set_disk(
    ctx: typer.Context,
    disk: str = typer.Argument(..., help="Disk name or ID."),
    label: str = typer.Option(None, "--label", help="New name."),
    new_hardlinks: str = typer.Option(None, "--new-hardlinks",
                                      help="Folder for new reseed hardlinks ('' = first seeding)."),
    uploads: str = typer.Option(None, "--uploads", help="Folder where uploads seed ('' = first seeding)."),
    watch: str = typer.Option(None, "--watch", help="Watched folder for your releases ('' = none)."),
):
    """Change the name or the single-purpose folders of a disk."""
    client = api(ctx)
    found = _disk(client, disk)
    body = {k: v for k, v in {"label": label, "new_torrent_rel_path": new_hardlinks, "upload_rel_path": uploads,
                              "watch_rel_path": watch}.items() if v is not None}
    if not body:
        raise fail("Nothing to change: pass --label, --new-hardlinks, --uploads or --watch.", EXIT_USAGE)
    updated = client.patch(f"/api/disks/{found['id']}", body)
    emit(state(ctx), updated, lambda d: _render_disks([d]))


@app.command("rm")
def remove_disk(ctx: typer.Context, disk: str = typer.Argument(..., help="Disk name or ID."),
                yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation.")):
    """Remove a disk from Nazgarr (nothing is deleted on the disk)."""
    client = api(ctx)
    found = _disk(client, disk)
    confirm(f"Remove disk {found['label']} from Nazgarr? Nothing is deleted on the disk.", yes)
    client.delete(f"/api/disks/{found['id']}")
    console.print(f"Disk {found['label']} removed.")


@app.command("test")
def test_disk(ctx: typer.Context, disk: str = typer.Argument(..., help="Disk name or ID.")):
    """Check the folders and create a test hardlink between them (an empty hidden file, removed right away)."""
    client = api(ctx)
    found = _disk(client, disk)
    result = client.post(f"/api/disks/{found['id']}/verify")

    def render(r: dict) -> None:
        for check in r.get("checks") or []:
            mark = {"ok": "[green]ok[/green]", "warning": "[yellow]note[/yellow]", "error": "[red]fail[/red]"}
            params = ", ".join(f"{k}={v}" for k, v in (check.get("params") or {}).items() if v is not None)
            console.print(f"{mark.get(check['level'], check['level']):>14}  {check['code']}  {params}")
        console.print("[green]Disk OK.[/green]" if r["consistent"] else "[red]The disk has problems.[/red]")

    emit(state(ctx), result, render)
    if not result["consistent"]:
        raise typer.Exit(1)


@app.command("browse")
def browse(ctx: typer.Context, disk: str = typer.Argument(..., help="Disk name or ID."),
           path: str = typer.Argument("", help="Folder inside the disk.")):
    """List a folder of the disk (to find the paths to add)."""
    client = api(ctx)
    found = _disk(client, disk)
    data = client.get(f"/api/disks/{found['id']}/browse", path=path)
    emit(state(ctx), data, lambda d: [console.print(
        f"{'[bold blue]' + e['name'] + '/[/bold blue]' if e['is_dir'] else e['name']}"
        + ("" if e["is_dir"] else f"  {size(e.get('size_bytes'))}")) for e in d["entries"]])


@app.command("mkdir")
def mkdir(ctx: typer.Context, disk: str = typer.Argument(..., help="Disk name or ID."),
          path: str = typer.Argument(..., help="New folder, relative to the disk.")):
    """Create a folder on the disk."""
    client = api(ctx)
    found = _disk(client, disk)
    data = client.post(f"/api/disks/{found['id']}/mkdir", {"path": path})
    emit(state(ctx), data, lambda d: console.print(f"Created {d['path']}."))


@folder_app.command("add")
def add_folder(
    ctx: typer.Context,
    disk: str = typer.Argument(..., help="Disk name or ID."),
    kind: str = typer.Argument(..., help="media or seeding."),
    path: str = typer.Argument(..., help="Folder relative to the disk, e.g. torrents."),
):
    """Add a media or seeding folder (same filesystem, never inside another one)."""
    if kind not in KINDS:
        raise fail("The kind is media or seeding.", EXIT_USAGE)
    client = api(ctx)
    found = _disk(client, disk)
    updated = client.post(f"/api/disks/{found['id']}/folders", {"kind": kind, "relative_path": path})
    emit(state(ctx), updated, lambda d: console.print(
        f"{kind.capitalize()} folder {path} added to {d['label']}: its files come in with the next scan."))


@folder_app.command("rm")
def remove_folder(
    ctx: typer.Context,
    disk: str = typer.Argument(..., help="Disk name or ID."),
    kind: str = typer.Argument(..., help="media or seeding."),
    path: str = typer.Argument(..., help="The folder to remove."),
):
    """Remove a folder from the disk (nothing changes on disk)."""
    client = api(ctx)
    found = _disk(client, disk)
    folder = next((f for f in found.get("folders") or [] if f["kind"] == kind and f["relative_path"] == path), None)
    if folder is None or folder.get("id") is None:
        raise fail(f"{found['label']} has no {kind} folder {path!r}.", EXIT_USAGE)
    updated = client.delete(f"/api/disks/{found['id']}/folders/{folder['id']}")
    emit(state(ctx), updated, lambda d: console.print(f"Folder {path} removed from {d['label']}."))
    err_console.print("Its files leave the library at the next scan.")
