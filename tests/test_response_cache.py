"""Cache delle viste della libreria (nazgarr/web/response_cache.py): ETag sulla
versione dei dati, 304 se il browser ha già quella versione, ricalcolo solo
quando cambia; gzip sulle risposte grandi."""

from nazgarr.library import states as library


def test_same_version_answers_304_without_recomputing(client, monkeypatch):
    calls = []
    real = library.media_file_states
    monkeypatch.setattr(library, "media_file_states", lambda *a, **k: calls.append(1) or real(*a, **k))

    first = client.get("/api/media-files")
    etag = first.headers["etag"]
    again = client.get("/api/media-files", headers={"If-None-Match": etag})
    other_client = client.get("/api/media-files")  # senza ETag: stessa versione, dalla cache in memoria

    assert first.status_code == 200 and again.status_code == 304 and other_client.status_code == 200
    assert other_client.json() == first.json()
    assert len(calls) == 1
    assert first.headers["cache-control"] == "private, no-cache"


def test_a_change_that_affects_the_views_changes_the_version(client):
    etag = client.get("/api/media-files").headers["etag"]
    client.put("/api/settings/exclusion_patterns", json={"value": "*.nfo"})

    after = client.get("/api/media-files", headers={"If-None-Match": etag})

    assert after.status_code == 200
    assert after.headers["etag"] != etag


def test_large_responses_are_gzipped(client):
    response = client.get("/api/health", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200  # piccola: sotto la soglia, nessun obbligo di gzip
    big = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert big.headers.get("content-encoding") == "gzip"


def test_disks_folders_and_removed_torrents_change_the_version(client):
    """Cambi che arrivano fuori da una run: un disco aggiunto o tolto, le sue
    cartelle, un torrent rimosso dal client (Non importati)."""
    from datetime import UTC, datetime

    from nazgarr.core.models import ClientTorrent, TorrentClient

    def etag():
        return client.get("/api/seed-files").headers["etag"]

    first = etag()
    root = client.scan_root / "disk1"
    (root / "torrents").mkdir(parents=True)
    disk_id = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(root)}).json()["id"]
    with_disk = etag()
    client.patch(f"/api/disks/{disk_id}", json={"torrents_rel_path": "torrents"})
    with_folder = etag()

    session = client.app.state.session_factory()
    try:
        tc = TorrentClient(label="qb", adapter_type="qbittorrent", base_url="http://qb:8080")
        session.add(tc)
        session.commit()
        ct = ClientTorrent(torrent_client_id=tc.id, info_hash="a" * 40, name="X", save_path="/x", state="uploading",
                           last_polled_at=datetime.now(UTC))
        session.add(ct)
        session.commit()
        with_torrent = etag()
        session.delete(ct)
        session.commit()
    finally:
        session.close()
    removed = etag()

    assert len({first, with_disk, with_folder, with_torrent, removed}) == 5


def test_requests_that_arrive_together_compute_the_view_once(client):
    # Misurato (2026-10-10): i calcoli doppi in parallelo alla fine di una
    # scansione portavano il processo da ~190 a ~430 MB.
    import threading
    import time

    from starlette.requests import Request

    from nazgarr.web import response_cache

    calls = []

    def compute():
        calls.append(1)
        time.sleep(0.2)
        return {"rows": list(range(10))}

    bodies = []

    def request_view():
        session = client.app.state.session_factory()
        try:
            request = Request({"type": "http", "headers": []})
            bodies.append(response_cache.cached_json(request, session, "test:view", compute).body)
        finally:
            session.close()

    threads = [threading.Thread(target=request_view) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert len(bodies) == 6 and len(set(bodies)) == 1
