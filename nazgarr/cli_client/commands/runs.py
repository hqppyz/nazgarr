"""nazgarr scan e nazgarr runs: le scansioni (lettura di dischi e client,
ricerca sui tracker). Una scansione legge e basta: niente viene collegato,
aggiunto o spostato."""

import time

import typer
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn

from nazgarr.cli_client.context import api, state
from nazgarr.cli_client.output import confirm, console, emit, err_console, table

app = typer.Typer(help="Scans: list, follow, cancel.", no_args_is_help=True)
POLL_SECONDS = 1.0


def _summary(run: dict) -> str:
    state_text = ("cancelled" if run.get("cancelled") else "finished" if run.get("finished_at") else
                  f"running: {run.get('current_phase') or '…'}")
    return (f"#{run['id']} {run['run_type']} · {state_text} · scanned {run['items_scanned']} · "
            f"matches {run['matches_found']} · waiting for review {run['pending_review']} · errors {run['errors']}")


def _follow(client, run: dict) -> dict:
    with Progress(TextColumn("{task.description}"), BarColumn(), TaskProgressColumn(), console=console,
                  transient=True) as progress:
        task = progress.add_task("Starting…", total=None)
        while not run.get("finished_at"):
            time.sleep(POLL_SECONDS)
            run = client.get(f"/api/runs/{run['id']}")
            label = f"{run.get('current_phase') or 'working'}: {run.get('phase_detail') or ''}".strip(": ")
            progress.update(task, description=label, total=run.get("phase_total"), completed=run.get("phase_done") or 0)
    return run


def scan(
    ctx: typer.Context,
    wait: bool = typer.Option(False, "--wait", "-w", help="Follow the scan until it ends."),
):
    """Start a scan: disks, torrent clients, matching on the trackers.

    It only reads: nothing is linked, added or moved. Matches wait in the
    review queue (nazgarr review ls).
    """
    client = api(ctx)
    run = client.post("/api/runs")
    if wait and not state(ctx).json:
        try:
            run = _follow(client, run)
        except KeyboardInterrupt:
            err_console.print(f"Still running in the background: nazgarr runs show {run['id']}")
            raise typer.Exit(0) from None
    elif wait:
        while not run.get("finished_at"):
            time.sleep(POLL_SECONDS)
            run = client.get(f"/api/runs/{run['id']}")
    emit(state(ctx), run, lambda r: console.print(_summary(r)))


@app.command("ls")
def list_runs(ctx: typer.Context, limit: int = typer.Option(10, "--limit", "-n", help="How many, newest first.")):
    """The latest scans."""
    runs = api(ctx).get("/api/runs")[:limit]
    emit(state(ctx), runs, lambda data: table(
        ["ID", "Type", "Started", "Finished", "Scanned", "Matches", "Review", "Errors"],
        [(r["id"], r["run_type"], r["started_at"], r.get("finished_at") or "running", r["items_scanned"],
          r["matches_found"], r["pending_review"], r["errors"]) for r in data]))


@app.command("show")
def show_run(ctx: typer.Context, run_id: int = typer.Argument(..., help="The scan ID."),
             follow: bool = typer.Option(False, "--follow", "-f", help="Follow it until it ends.")):
    """One scan, with its errors."""
    client = api(ctx)
    run = client.get(f"/api/runs/{run_id}")
    if follow and not run.get("finished_at") and not state(ctx).json:
        run = _follow(client, run)

    def render(r: dict) -> None:
        console.print(_summary(r))
        for message in r.get("error_messages") or []:
            err_console.print(f"  [red]•[/red] {message}")

    emit(state(ctx), run, render)


@app.command("cancel")
def cancel_run(ctx: typer.Context, run_id: int = typer.Argument(..., help="The scan ID."),
               yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation.")):
    """Stop a running scan (what it already saved stays)."""
    confirm(f"Stop scan #{run_id}?", yes)
    run = api(ctx).post(f"/api/runs/{run_id}/cancel")
    emit(state(ctx), run, lambda r: console.print(f"Stop requested for scan #{r['id']}."))
