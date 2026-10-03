"""nazgarr library, nazgarr triage e nazgarr logs: guardare, senza cambiare
niente (tranne `library search`, che cerca subito sui tracker, e `library
exclude`, che aggiunge un'esclusione: nessun file viene toccato)."""

import time

import typer

from nazgarr.cli_client.context import api, state
from nazgarr.cli_client.helpers import find, human_duration
from nazgarr.cli_client.output import EXIT_USAGE, console, emit, fail, size, table

library_app = typer.Typer(help="The library: what seeds, what does not.", no_args_is_help=True)
triage_app = typer.Typer(help="Triage: torrents seeding without a hardlink in the library.", no_args_is_help=True)


def _item_ref(ref: str) -> tuple[str, int]:
    kind, _, number = ref.partition("/")
    if kind not in ("movie", "tv") or not number.isdigit():
        raise fail("Name the item as movie/TMDB_ID or tv/TMDB_ID (see `nazgarr library ls`).", EXIT_USAGE)
    return kind, int(number)


@library_app.command("ls")
def library_ls(
    ctx: typer.Context,
    content_type: str = typer.Option(None, "--type", help="movie or tv."),
    orphans: bool = typer.Option(False, "--orphans", help="Only items with files that seed nowhere."),
    search: str = typer.Option(None, "--search", "-s", help="Text in the title."),
    disk: str = typer.Option(None, "--disk", help="Only this disk."),
    tracker: str = typer.Option(None, "--tracker", help="Count only this tracker's torrents (ID)."),
):
    """The library, one row per movie or episode group."""
    client = api(ctx)
    disk_id = find(client.get("/api/disks"), disk, "disk")["id"] if disk else None
    items = client.get("/api/library/items", disk_id=disk_id, tracker=tracker)
    if content_type:
        items = [i for i in items if i["content_type"] == content_type]
    if search:
        items = [i for i in items if search.lower() in (i.get("title") or "").lower()]
    if orphans:
        items = [i for i in items if any(f["state"] != "seeding" and not f["excluded"] for f in i["files"])]

    def render(data: list[dict]) -> None:
        rows = []
        for i in data:
            files = [f for f in i["files"] if not f["excluded"]]
            seeding = sum(1 for f in files if f["state"] == "seeding")
            episode = f" S{i['season_number']:02d}" if i.get("season_number") is not None else ""
            rows.append((f"{i['content_type']}/{i['tmdb_id']}", f"{i.get('title')}{episode}", i.get("year") or "",
                         f"{seeding}/{len(files)}", size(sum(f["size_bytes"] for f in files))))
        table(["Item", "Title", "Year", "Seeding", "Size"], rows)

    emit(state(ctx), items, render)


@library_app.command("show")
def library_show(ctx: typer.Context, ref: str = typer.Argument(..., help="movie/TMDB_ID or tv/TMDB_ID.")):
    """One item: its files, where they seed, the trackers."""
    kind, number = _item_ref(ref)
    data = api(ctx).get(f"/api/library/items/{kind}/{number}")

    def render(d: dict) -> None:
        console.print(f"[bold]{d.get('title')}[/bold] ({d.get('year') or ''}) · {kind}/{number}")
        table(["File", "State", "Size"], [
            (f["relative_path"], f["state"] + (" · excluded" if f.get("excluded") else ""), size(f["size_bytes"]))
            for f in d.get("files") or []])

    emit(state(ctx), data, render)


@library_app.command("search")
def library_search(ctx: typer.Context, ref: str = typer.Argument(..., help="movie/TMDB_ID or tv/TMDB_ID.")):
    """Search this item on the trackers now (proposals go to the review queue)."""
    kind, number = _item_ref(ref)
    data = api(ctx).post(f"/api/library/items/{kind}/{number}/search")
    emit(state(ctx), data, lambda d: console.print(
        f"Searched {d['files_searched']} file(s): {d['candidates']} candidate(s)"
        + (" (some trackers were rate limited)" if d.get("rate_limited") else "")
        + ". See `nazgarr review ls`."))


@library_app.command("exclude")
def library_exclude(ctx: typer.Context,
                    path: str = typer.Argument(..., help="File or folder, relative to its disk."),
                    folder: bool = typer.Option(False, "--folder", help="A folder: everything inside it.")):
    """Leave a file or folder out of states, counts and searches (it stays on disk)."""
    data = api(ctx).post("/api/library/exclude", {"relative_path": path, "is_dir": folder})
    emit(state(ctx), data, lambda d: console.print(f"Excluded with the pattern {d['pattern']}"))


@triage_app.command("ls")
def triage_ls(
    ctx: typer.Context,
    safe: bool = typer.Option(False, "--safe", help="Only the ones safe to remove."),
    category: str = typer.Option(None, "--category",
                                 help="superseded, copy, removed, never_imported or extras_only."),
    excluded: bool = typer.Option(False, "--excluded", help="Show the excluded ones too."),
):
    """Torrents seeding without a hardlink in the library, with the reason."""
    data = api(ctx).get("/api/torrents/not-imported")
    rows = [t for t in data["torrents"] if (excluded or not t.get("excluded"))
            and (not category or t["category"] == category)
            and (not safe or ((t.get("seed_requirement") or {}).get("status") == "met"
                              and not t.get("removal_warnings")))]

    def removable(t: dict) -> str:
        req = t.get("seed_requirement") or {}
        if req.get("status") == "met":
            text = "OK"
        elif req.get("status") == "pending":
            left = req.get("remaining") or {}
            text = "left " + " ".join(filter(None, (human_duration(int(left["seed_time_seconds"]))
                                                    if left.get("seed_time_seconds") else "",
                                                    f"ratio +{left['ratio']:.2f}" if left.get("ratio") else "")))
        else:
            text = "-"
        warnings = t.get("removal_warnings") or []
        return text + (f" ⚠ {', '.join(w['code'] for w in warnings)}" if warnings else "")

    def render(_rows: list[dict]) -> None:
        if not data.get("classified"):
            console.print("Not computed yet: it runs after a scan (or `nazgarr triage refresh`).")
            return
        table(["Torrent", "Why", "Tracker", "Size", "Ratio", "Removable"], [
            (t["name"], t["category"], t.get("tracker") or "", size(t["total_bytes"]),
             f"{t['ratio']:.2f}" if t.get("ratio") is not None else "", removable(t)) for t in _rows])

    emit(state(ctx), rows, render)


@triage_app.command("refresh")
def triage_refresh(ctx: typer.Context):
    """Compute the triage again now."""
    data = api(ctx).post("/api/torrents/not-imported/refresh")
    emit(state(ctx), data, lambda d: console.print(f"Triage computed: {len(d.get('torrents') or [])} torrent(s)."))


def logs(
    ctx: typer.Context,
    level: str = typer.Option("INFO", "--level", "-l", help="Minimum level: DEBUG, INFO, WARNING, ERROR."),
    lines: int = typer.Option(50, "--lines", "-n", help="How many of the latest lines."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Keep printing new lines."),
):
    """The application log."""
    client = api(ctx)
    seen: set = set()

    def fetch() -> list[dict]:
        return client.get("/api/system/logs", min_level=level.upper()).get("entries") or []

    entries = fetch()[-lines:]
    if state(ctx).json and not follow:
        emit(state(ctx), entries, lambda _e: None)
        return

    def show(batch: list[dict]) -> None:
        for e in batch:
            key = (e["timestamp"], e["logger"], e["message"])
            if key in seen:
                continue
            seen.add(key)
            colour = {"ERROR": "red", "WARNING": "yellow", "DEBUG": "dim"}.get(e["level"], "")
            text = f"{e['timestamp']} {e['level']:<7} {e['logger']}: {e['message']}"
            console.print(f"[{colour}]{text}[/{colour}]" if colour else text, markup=bool(colour))

    show(entries)
    while follow:
        try:
            time.sleep(2)
            show(fetch())
        except KeyboardInterrupt:
            break
