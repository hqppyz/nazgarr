"""nazgarr review: la coda delle proposte di reseeding. Approvare crea gli
hardlink e aggiunge il torrent al client: chiede sempre conferma (--yes per
gli script), come la regola del progetto vuole."""

import typer

from nazgarr.cli_client.context import api, state
from nazgarr.cli_client.output import confirm, console, emit, table

app = typer.Typer(help="The reseeding review queue: list, approve, reject, retry.", no_args_is_help=True)


def _row(r: dict) -> tuple:
    verify = r.get("verify_status") or ""
    return (r["id"], r["direction"].replace("_", "→"), f"{r['confidence'] * 100:.0f}%", r["candidate_name"],
            r["status"], verify, r.get("ambiguity_reason") or "")


@app.command("ls")
def list_reviews(ctx: typer.Context):
    """The proposals waiting for you."""
    rows = api(ctx).get("/api/reviews")
    emit(state(ctx), rows, lambda data: table(
        ["ID", "Direction", "Confidence", "Torrent", "Status", "Check", "Note"], [_row(r) for r in data]))


@app.command("show")
def show_review(ctx: typer.Context, review_id: int = typer.Argument(..., help="The review ID.")):
    """One proposal, with what it would do."""
    found = next((r for r in api(ctx).get("/api/reviews") if r["id"] == review_id), None)
    if found is None:
        from nazgarr.cli_client.output import fail
        raise fail(f"No review #{review_id} waiting.")

    def render(r: dict) -> None:
        table(["ID", "Direction", "Confidence", "Torrent", "Status", "Check", "Note"], [_row(r)])
        layout = r.get("layout") or {}
        if layout:
            console.print(f"Files: {layout}")
        if r.get("seeding_on"):
            console.print(f"Already seeding on: {', '.join(map(str, r['seeding_on']))}")

    emit(state(ctx), found, render)


@app.command("approve")
def approve(ctx: typer.Context, review_ids: list[int] = typer.Argument(..., help="One or more review IDs."),
            yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation.")):
    """Approve: hardlinks are created and the torrent is added to its client.

    With the full check on (the default) every piece is read first; the
    execution follows only if it passes.
    """
    confirm(f"Approve {len(review_ids)} proposal(s)? Files get hardlinked and torrents added to the client.", yes)
    client = api(ctx)
    done = [client.post(f"/api/reviews/{rid}/approve") for rid in review_ids]
    emit(state(ctx), done, lambda data: [console.print(
        f"#{r['id']}: {r['status']}" + (f" ({r['verify_status']})" if r.get("verify_status") else "")) for r in data])


@app.command("reject")
def reject(ctx: typer.Context, review_ids: list[int] = typer.Argument(..., help="One or more review IDs.")):
    """Reject: the proposal goes away, nothing is touched."""
    client = api(ctx)
    done = [client.post(f"/api/reviews/{rid}/reject") for rid in review_ids]
    emit(state(ctx), done, lambda data: [console.print(f"#{r['id']}: {r['status']}") for r in data])


@app.command("failed")
def failed(ctx: typer.Context):
    """Executions that failed, to retry."""
    rows = api(ctx).get("/api/reviews/failed")
    emit(state(ctx), rows, lambda data: table(
        ["Seed job", "Torrent", "Tracker", "Client", "Error"],
        [(r["id"], r.get("candidate_name"), r.get("tracker"), r.get("torrent_client"),
          r.get("error_message") or r.get("display_status") or r["final_status"]) for r in data]))


@app.command("retry")
def retry(ctx: typer.Context, seed_job_id: int = typer.Argument(..., help="The failed seed job ID."),
          yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation.")):
    """Retry a failed execution (hardlinks and torrent add again)."""
    confirm(f"Retry seed job #{seed_job_id}? Files get hardlinked and the torrent added to the client.", yes)
    result = api(ctx).post(f"/api/reviews/failed/{seed_job_id}/retry")
    emit(state(ctx), result, lambda r: console.print(f"Seed job #{seed_job_id} retried."))
