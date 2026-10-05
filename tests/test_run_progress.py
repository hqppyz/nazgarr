"""Avanzamento live di una run (nazgarr/core/run_progress.py) come lo legge il popup
di stato: fasi, x/y, dettaglio, file saltati, attese per rate limit."""

import json
from datetime import UTC, datetime

import httpx

from nazgarr.adapters.tracker.base import Unit3dTrackerAdapter
from nazgarr.api.runs import RunResponse
from nazgarr.core.models import Disk, MediaFile, MediaItem, Tracker
from nazgarr.core.run_progress import PHASES, RunProgress
from nazgarr.library import scanner
from nazgarr.reseed import matching, pipeline


def _disk_with_files(db_session, tmp_path, media=3, seeds=2):
    for i in range(media):
        path = tmp_path / "media" / f"m{i}.mkv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * (i + 1))
    for i in range(seeds):
        path = tmp_path / "torrents" / f"s{i}.mkv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"y" * (i + 1))
    disk = Disk(label="Disk1", root_path=str(tmp_path), media_rel_path="media", torrents_rel_path="torrents")
    db_session.add(disk)
    db_session.commit()
    return disk


def test_a_full_run_records_every_phase_with_totals(db_session, tmp_path):
    _disk_with_files(db_session, tmp_path)
    run = pipeline.start_run(db_session, "manual")

    pipeline.run_bulk_import(db_session, run, str(tmp_path / "data"))

    phases = json.loads(run.phases_json)
    assert list(phases) == list(PHASES)
    assert all(p["status"] == "done" for p in phases.values())
    assert (phases["scanning"]["done"], phases["scanning"]["total"]) == (5, 5)
    assert run.current_phase is None and run.phase_detail is None

    response = RunResponse.from_model(run)
    assert response.phases["scanning"].total == 5
    assert response.items_scanned == 5


def test_scan_progress_is_visible_while_the_disk_is_being_scanned(db_session, tmp_path, monkeypatch):
    _disk_with_files(db_session, tmp_path)
    run = pipeline.start_run(db_session, "manual")
    seen = []
    real_scan = scanner.scan_disk

    def spying_scan(session, disk, run_, files=None, on_progress=None):
        def spy(n):
            on_progress(n)
            seen.append((run_.current_phase, run_.phase_done, run_.phase_total, run_.phase_detail))
        return real_scan(session, disk, run_, files=files, on_progress=spy)

    monkeypatch.setattr(scanner, "scan_disk", spying_scan)
    pipeline.run_bulk_import(db_session, run, str(tmp_path / "data"))

    assert seen[0] == ("scanning", 1, 5, "Disk1 (1/1)")
    assert seen[-1] == ("scanning", 5, 5, "Disk1 (1/1)")


def test_matching_counts_recently_searched_files_as_skipped(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    disk = _disk_with_files(db_session, tmp_path, media=2, seeds=0)
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    item = MediaItem(content_type="movie", tmdb_id=1)
    db_session.add_all([tracker, item])
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    for i in range(2):
        db_session.add(MediaFile(
            disk_id=disk.id, relative_path=f"media/m{i}.mkv", size_bytes=i + 1, st_dev=1, inode=i,
            media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        ))
    db_session.commit()

    class Empty:
        def search_by_tmdb(self, tmdb_id):
            return []

    matching.run_media_to_torrent_matching(db_session, tracker, Empty())  # prima ricerca
    progress = RunProgress(db_session, run)
    progress.start_phase("matching", total=0)
    matching.run_media_to_torrent_matching(db_session, tracker, Empty(), progress=progress)
    progress.finish()

    state = json.loads(run.phases_json)["matching"]
    assert (state["done"], state["total"], state["skipped"]) == (2, 2, 2)


def test_rate_limit_wait_is_announced_and_cleared():
    responses = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={"data": []})]
    client = httpx.Client(transport=httpx.MockTransport(lambda r: responses.pop(0)), base_url="https://t.example")
    adapter = Unit3dTrackerAdapter("https://t.example", "tok", http_client=client, sleep=lambda s: None)
    notices = []
    adapter.on_rate_limit_wait = notices.append

    adapter.search_by_tmdb(1)

    assert notices == [7.0, None]


def test_runs_left_open_by_a_restart_are_closed_with_a_visible_error(db_session):
    run = pipeline.start_run(db_session, "manual")
    progress = RunProgress(db_session, run)
    progress.start_phase("matching", total=100)
    progress.advance(40)

    closed = pipeline.close_interrupted_runs(db_session)

    assert closed == 1
    assert run.finished_at is not None and run.current_phase is None
    assert run.errors == 1
    assert "matching" in run.last_error
    assert pipeline.close_interrupted_runs(db_session) == 0


def test_stop_request_ends_the_run_cleanly_at_the_next_progress_update(db_session, tmp_path, monkeypatch):
    from nazgarr.core.models import RunLog

    _disk_with_files(db_session, tmp_path)
    run = pipeline.start_run(db_session, "manual")
    real_scan = scanner.scan_disk

    def scan_then_stop(session, disk, run_, files=None, on_progress=None):
        # Come farebbe POST /api/runs/{id}/cancel da un'altra sessione.
        session.query(RunLog).filter_by(id=run_.id).update({"cancel_requested_at": datetime.now(UTC)})
        session.commit()
        return real_scan(session, disk, run_, files=files, on_progress=on_progress)

    monkeypatch.setattr(scanner, "scan_disk", scan_then_stop)
    monkeypatch.setattr("nazgarr.core.run_progress.COMMIT_EVERY", 1)
    pipeline.run_bulk_import(db_session, run, str(tmp_path / "data"))

    assert run.finished_at is not None
    assert run.last_error == "Stopped by the user during 'scanning'"
    assert run.errors == 0  # uno stop voluto non è un errore
    assert set(json.loads(run.phases_json)) == {"scanning"}  # nessuna fase successiva avviata
    response = RunResponse.from_model(run)
    assert response.cancelled is True and response.current_phase is None


def test_cancel_endpoint(client):
    trigger = client.post("/api/runs")
    run_id = trigger.json()["id"]

    # La run del TestClient finisce subito (BackgroundTasks sincroni): stop tardivo = 409.
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 409
    assert client.post("/api/runs/9999/cancel").status_code == 404
