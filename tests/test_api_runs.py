import time


def _create_disk_with_hardlinked_file(client):
    root = client.scan_root / "disk1"
    (root / "media" / "movies").mkdir(parents=True)
    (root / "torrents").mkdir(parents=True)

    disk_id = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(root)}).json()["id"]
    client.patch(
        f"/api/disks/{disk_id}",
        json={"torrents_rel_path": "torrents", "media_rel_path": "media/movies"},
    )

    media_file = root / "media" / "movies" / "Movie.2024.mkv"
    media_file.write_bytes(b"content")
    import os

    os.link(media_file, root / "torrents" / "Movie.2024.mkv")
    return disk_id


def test_trigger_bulk_import_and_poll_until_finished(client):
    _create_disk_with_hardlinked_file(client)

    trigger = client.post("/api/runs")
    assert trigger.status_code == 202
    run_id = trigger.json()["id"]

    # BackgroundTasks in TestClient viene eseguito prima che la response
    # torni al chiamante (starlette lo esegue in-process, sincrono rispetto
    # al `with` del TestClient) — niente polling reale necessario, ma
    # verifichiamo comunque lo stato finale via GET.
    for _ in range(20):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["finished_at"] is not None:
            break
        time.sleep(0.05)

    assert run["finished_at"] is not None
    assert run["errors"] == 0
    assert run["items_scanned"] == 2

    # Nessun client torrent configurato in questo test (copre solo il
    # trigger/poll della run) — l'hardlink è comunque rilevato, ma senza
    # tracciamento client lo stato "seeding" pieno richiede Fase 2
    # (vedi tests/test_library_states.py per la copertura completa).
    media_files = client.get("/api/media-files").json()
    seed_files = client.get("/api/seed-files").json()
    assert seed_files[0]["media_file_id"] == media_files[0]["id"]


def test_a_second_run_is_refused_while_one_is_in_progress(client):
    """Due run insieme scriverebbero le stesse tabelle (e con l'esecuzione
    automatica potrebbero eseguire due volte la stessa review)."""
    from nazgarr.reseed import pipeline

    session = client.app.state.session_factory()
    try:
        running = pipeline.start_run(session, run_type="bulk_import")  # rimasta in corso
        response = client.post("/api/runs")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "run_in_progress"
        from nazgarr.core.models import RunLog

        assert [r.id for r in session.query(RunLog).all()] == [running.id]
    finally:
        session.close()


def test_the_list_is_bounded_and_pages_back(client):
    """Audit 2026-10-18: tutte le run, mai sfoltite, a ogni poll di 3 s."""
    from datetime import UTC, datetime

    from nazgarr.reseed import pipeline

    session = client.app.state.session_factory()
    try:
        ids = []
        for _ in range(5):
            run = pipeline.start_run(session, run_type="scheduled")
            run.finished_at = datetime.now(UTC)
            session.commit()
            ids.append(run.id)
    finally:
        session.close()

    newest = client.get("/api/runs", params={"limit": 2}).json()
    older = client.get("/api/runs", params={"limit": 2, "before_id": newest[-1]["id"]}).json()

    assert [r["id"] for r in newest] == ids[::-1][:2]
    assert [r["id"] for r in older] == ids[::-1][2:4]
    assert len(client.get("/api/runs").json()) == 5  # il default resta ampio (CLI)
    assert client.get("/api/runs", params={"limit": 0}).status_code == 422
