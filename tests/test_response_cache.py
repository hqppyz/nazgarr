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


# --- la versione vede ogni scrittura (audit 2026-10-18) -----------------------------------


def test_a_webhook_delete_and_a_same_name_upgrade_change_the_version(db_session, tmp_path):
    """Prima la versione era un'impronta di conteggi e massimi: un file tolto
    da un webhook (solo last_scan_id che torna indietro) o sostituito con lo
    stesso nome (un UPDATE in place) non la cambiavano, e le viste restavano
    quelle di prima fino alla run successiva."""
    from datetime import UTC, datetime, timedelta

    from nazgarr.core.models import ArrWebhookEvent
    from nazgarr.integrations import arr_webhooks
    from nazgarr.web import response_cache
    from tests.test_arr_webhooks import _download, _library, _radarr

    def _event(session, source, instance, payload):
        arr_webhooks.receive(session, source, instance, payload)
        arr_webhooks.process_pending(session, now=datetime.now(UTC) + timedelta(minutes=1))
        return session.query(ArrWebhookEvent).order_by(ArrWebhookEvent.id.desc()).first()

    root, _disk = _library(db_session, tmp_path)
    folder = root / "media" / "movies" / "The Matrix (1999)"
    folder.mkdir()
    (folder / "The Matrix (1999).mkv").write_bytes(b"o" * 50)
    radarr = _radarr(db_session)
    path = "/movies/The Matrix (1999)/The Matrix (1999).mkv"
    _event(db_session, "radarr", radarr, _download(path, 50))
    before_upgrade = response_cache.data_version(db_session)

    (folder / "The Matrix (1999).mkv").write_bytes(b"n" * 80)  # upgrade con lo stesso nome
    _event(db_session, "radarr", radarr, _download(path, 80, deleted=[{"path": path, "size": 50}]))
    before_delete = response_cache.data_version(db_session)

    (folder / "The Matrix (1999).mkv").unlink()
    event = _event(db_session, "radarr", radarr, {"eventType": "MovieFileDelete", "movie": {"tmdbId": 603},
                                                  "movieFile": {"path": path, "size": 80}})

    assert event.detail == "file removed"
    assert len({before_upgrade, before_delete, response_cache.data_version(db_session)}) == 3


def test_an_in_place_update_changes_the_version_and_a_rollback_does_not(db_session):
    from nazgarr.core.models import MediaItem, UploadJob
    from nazgarr.web import response_cache

    item = MediaItem(content_type="movie", tmdb_id=603)
    db_session.add(item)
    db_session.commit()
    first = response_cache.data_version(db_session)
    item.title = "The Matrix"
    db_session.commit()
    titled = response_cache.data_version(db_session)
    item.title = "Something else"
    db_session.flush()
    db_session.rollback()
    rolled_back = response_cache.data_version(db_session)
    # L'avanzamento di un upload si scrive ogni secondo e nessuna vista in cache lo legge.
    db_session.add(UploadJob(relative_path="x.mkv", source_path="/x.mkv"))
    db_session.commit()

    assert first != titled
    assert rolled_back == titled
    assert response_cache.data_version(db_session) == titled


def test_a_view_is_fresh_right_after_a_change_outside_a_run(client):
    """Un MediaItem rinominato fuori da una run: la vista si ricalcola, il
    vecchio ETag non dà più un 304."""
    from datetime import UTC, datetime

    from nazgarr.core.models import Disk, MediaItem
    from nazgarr.reseed import pipeline
    from tests.fakes import make_media_file

    session = client.app.state.session_factory()
    try:
        root = client.scan_root / "d"
        (root / "media").mkdir(parents=True)
        disk = Disk(label="d", root_path=str(root), media_rel_path="media")
        item = MediaItem(content_type="movie", tmdb_id=603, title="Old")
        session.add_all([disk, item])
        session.commit()
        run = pipeline.start_run(session, "manual")
        make_media_file(session, disk, "media/a.mkv", run, media_item_id=item.id)
        run.finished_at = datetime.now(UTC)
        session.commit()
        first = client.get("/api/library/items")
        item.title = "New"
        session.commit()
    finally:
        session.close()

    after = client.get("/api/library/items", headers={"If-None-Match": first.headers["etag"]})

    assert first.json()[0]["title"] == "Old"
    assert after.status_code == 200 and after.json()[0]["title"] == "New"


# --- memoria limitata (audit 2026-10-18) ----------------------------------------------------


def _request():
    from starlette.requests import Request

    return Request({"type": "http", "headers": []})


def test_bodies_of_a_past_version_leave_memory_and_the_cache_is_bounded(db_session, monkeypatch):
    from nazgarr.core.models import AppSetting
    from nazgarr.web import response_cache

    response_cache.clear()
    response_cache.cached_json(_request(), db_session, "old", lambda: {"v": 1})
    db_session.add(AppSetting(key="something", value="1"))
    db_session.commit()  # versione nuova: il corpo di prima non si servirà più
    response_cache.cached_json(_request(), db_session, "new", lambda: {"v": 2})
    assert [k.rsplit("|", 1)[1] for k in response_cache._cache] == ["new"]

    monkeypatch.setattr(response_cache, "MAX_ENTRIES", 3)
    for i in range(6):
        response_cache.cached_json(_request(), db_session, f"k{i}", lambda: {"rows": "x" * 100})
    assert [k.rsplit("|", 1)[1] for k in response_cache._cache] == ["k3", "k4", "k5"]

    monkeypatch.setattr(response_cache, "MAX_BYTES", 250)
    response_cache.cached_json(_request(), db_session, "big", lambda: {"rows": "y" * 200})
    assert [k.rsplit("|", 1)[1] for k in response_cache._cache] == ["big"]
    assert response_cache._cached_bytes == sum(len(body) for _v, _e, body in response_cache._cache.values())
    assert response_cache._computing == {}  # i lock per chiave non restano


def test_a_late_computation_of_a_past_version_keeps_the_fresh_bodies(db_session):
    """Revisione dell'audit 2026-10-18: un calcolo partito prima di un commit
    e finito dopo che un'altra vista era già in cache con la versione nuova
    toglieva quel corpo fresco e teneva il suo, che nessuno avrebbe più
    servito."""
    from nazgarr.core.models import AppSetting
    from nazgarr.web import response_cache

    response_cache.clear()
    old = response_cache.data_version(db_session)
    db_session.add(AppSetting(key="late", value="1"))
    db_session.commit()
    response_cache.cached_json(_request(), db_session, "fresh", lambda: {"v": 2})

    response_cache._store(f"{db_session.get_bind().url}|late", old, 'W/"late"', b'{"v":1}')

    assert [k.rsplit("|", 1)[1] for k in response_cache._cache] == ["fresh"]
    assert response_cache._cached_bytes == len(b'{"v":2}')


def test_tracker_values_share_one_canonical_key(client, monkeypatch):
    """'1' e '01' sono lo stesso tracker, un id che non esiste vale "all" e
    '²' non è più un 500: ogni valore diverso era un corpo in più in memoria."""
    from nazgarr.library import states as library

    tracker_id = client.post("/api/trackers", json={
        "label": "T", "base_url": "https://t.example", "announce_url": "https://t.example/announce/x",
        "adapter_type": "unit3d", "api_token": "tok"}).json()["id"]
    calls = []
    real = library.media_file_states
    monkeypatch.setattr(library, "media_file_states", lambda *a, **k: calls.append(k["tracker"]) or real(*a, **k))

    etags = {value: client.get("/api/media-files", params={"tracker": value}).headers["etag"]
             for value in (str(tracker_id), f"0{tracker_id}", "987654321", "all", "²", "9" * 5000)}

    assert etags[str(tracker_id)] == etags[f"0{tracker_id}"]
    assert etags["987654321"] == etags["all"] == etags["²"] == etags["9" * 5000]
    assert calls == [str(tracker_id), "all"]


def test_an_unknown_disk_is_a_404(client):
    assert client.get("/api/media-files", params={"disk_id": 999}).status_code == 404
    assert client.get("/api/library/items", params={"disk_id": 999}).status_code == 404
    assert client.get("/api/dashboard", params={"disk_id": 999}).json()["detail"]["code"] == "disk_not_found"
