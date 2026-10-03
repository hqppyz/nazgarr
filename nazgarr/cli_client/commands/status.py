"""nazgarr status: versione, configurazione, salute della libreria, ultima
scansione e coda degli upload, in un colpo d'occhio."""

import typer

from nazgarr.cli_client.context import api, state
from nazgarr.cli_client.output import console, emit, size

ACTIVE = ("identifying", "awaiting_match", "analyzing", "awaiting_decision", "queued", "running")


def status(ctx: typer.Context):
    """Version, setup checklist, library health, last scan and upload queue."""
    client = api(ctx)
    health = client.get("/api/health")
    setup = client.get("/api/system/setup-status")
    dashboard = client.get("/api/dashboard")
    uploads = client.get("/api/uploads")
    data = {
        "url": client.url, "version": health.get("version"), "setup": setup, "dashboard": dashboard,
        "uploads": {"active": sum(1 for u in uploads if u["status"] in ACTIVE),
                    "awaiting_you": sum(1 for u in uploads if u["status"] in ("awaiting_match", "awaiting_decision"))},
    }
    emit(state(ctx), data, _render)


def _render(data: dict) -> None:
    dash, setup = data["dashboard"], data["setup"]
    console.print(f"[bold]Nazgarr {data['version']}[/bold] at {data['url']}")
    missing = [step for step in setup["required"] if not setup["steps"].get(step, {}).get("done")]
    console.print("Setup: " + ("[green]complete[/green]" if not missing else
                               f"[yellow]missing {', '.join(missing)}[/yellow]"))
    if dash.get("total_media_size"):
        console.print(f"Library health: [bold]{dash['health_pct']:.0f}%[/bold] seeding "
                      f"({size(dash['seeding_media_size'])} of {size(dash['total_media_size'])})")
    triage = dash.get("not_imported_torrents") or 0
    console.print(f"Orphaned torrents: {dash['orphan_torrent_count']} · Triage: {triage}"
                  f" · Duplicates: {dash['duplicate_files']}")
    console.print(f"Reviews waiting: [bold]{dash['pending_review']}[/bold] · Failed: {dash['failed']}"
                  f" · Unmatched: {dash['unmatched']}")
    last = dash.get("last_run")
    console.print("Last scan: " + (f"#{last.get('id')} {last.get('finished_at') or 'running'}" if last else "never"))
    uploads = data["uploads"]
    console.print(f"Uploads in progress: {uploads['active']} (waiting for you: {uploads['awaiting_you']})")
