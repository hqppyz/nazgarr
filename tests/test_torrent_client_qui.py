"""Nessuna istanza qui reale disponibile in fase di sviluppo (vedi
docstring di nazgarr/adapters/torrent_client/qui.py) — questi test usano un
httpx.MockTransport che imita la superficie della sua API reale (verificata
contro il suo swagger/OpenAPI pubblico e contro l'integrazione qui di
Auditorr), non una connessione reale."""

import json

import httpx
import pytest

from nazgarr.adapters.torrent_client.base import TorrentAddTimeoutError
from nazgarr.adapters.torrent_client.qui import QuiTorrentClientAdapter

INSTANCE_ID = 7


class _QuiMock:
    def __init__(self, pages=None, files_by_hash=None, trackers_by_hash=None):
        self.pages = pages if pages is not None else [[]]
        self.files_by_hash = files_by_hash or {}
        self.trackers_by_hash = trackers_by_hash or {}
        self.added_calls: list[dict] = []
        self.bulk_actions: list[dict] = []
        self.next_hash = "new-hash"
        self.preferences = {}
        self.bodies: list[bytes] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "tok123"
        path = request.url.path
        method = request.method
        base = f"/api/instances/{INSTANCE_ID}"

        if method == "GET" and path == f"{base}/torrents":
            page = int(request.url.params.get("page", "0"))
            batch = self.pages[page] if page < len(self.pages) else []
            return httpx.Response(200, json={"torrents": batch, "total": sum(len(p) for p in self.pages)})

        if method == "POST" and path == f"{base}/torrents":
            is_file_upload = b'name="torrent"' in request.content
            is_url = b'name="urls"' in request.content
            self.added_calls.append({"is_file_upload": is_file_upload, "is_url": is_url})
            self.bodies.append(request.content)
            self.pages[0] = self.pages[0] + [
                {"hash": self.next_hash, "name": "x", "savePath": "/torrents/x", "state": "uploading", "progress": 0.0}
            ]
            return httpx.Response(201)

        if method == "POST" and path == f"{base}/torrents/bulk-action":
            self.bulk_actions.append(json.loads(request.content))
            return httpx.Response(200)

        if method == "GET" and path == f"{base}/preferences":
            return httpx.Response(200, json=self.preferences)

        if method == "GET" and path.endswith("/files"):
            h = path.rsplit("/", 2)[1]
            return httpx.Response(200, json=self.files_by_hash.get(h, []))

        if method == "GET" and path.endswith("/trackers"):
            h = path.rsplit("/", 2)[1]
            return httpx.Response(200, json=self.trackers_by_hash.get(h, []))

        return httpx.Response(404)


def _adapter(mock: _QuiMock, **kwargs):
    client = httpx.Client(
        transport=httpx.MockTransport(mock.handler), base_url="https://qui.example",
        headers={"X-API-Key": "tok123"},
    )
    return QuiTorrentClientAdapter(
        base_url="https://qui.example", api_token="tok123", instance_id=INSTANCE_ID,
        http_client=client, poll_interval=0.01, **kwargs
    )


def test_add_torrent_via_url_sends_urls_field_and_forces_recheck():
    mock = _QuiMock(
        pages=[[{"hash": "existing", "name": "e", "savePath": "/x", "state": "uploading", "progress": 1.0}]]
    )
    adapter = _adapter(mock)

    info_hash = adapter.add_torrent("magnet:?xt=...", save_path="/torrents/movie")

    assert info_hash == "new-hash"
    assert mock.added_calls[0] == {"is_file_upload": False, "is_url": True}
    # Il recheck e poi l'avvio: un reseed deve seedare anche con le preferenze
    # "non avviare automaticamente" del qBittorrent dietro.
    assert mock.bulk_actions == [{"hashes": ["new-hash"], "action": "recheck"},
                                 {"hashes": ["new-hash"], "action": "resume"}]


def test_add_torrent_via_local_file_sends_torrent_field(tmp_path):
    torrent_path = tmp_path / "movie.torrent"
    torrent_path.write_bytes(b"d8:announce...")
    mock = _QuiMock()
    adapter = _adapter(mock)

    info_hash = adapter.add_torrent(str(torrent_path), save_path="/torrents/movie")

    assert info_hash == "new-hash"
    assert mock.added_calls[0] == {"is_file_upload": True, "is_url": False}


def test_add_torrent_sends_the_content_layout():
    mock = _QuiMock()
    _adapter(mock).add_torrent("magnet:?xt=...", save_path="/torrents/movie")
    assert b'name="contentLayout"\r\n\r\nOriginal' in mock.bodies[0]
    assert b'name="paused"\r\n\r\nfalse' in mock.bodies[0]


@pytest.mark.parametrize(("prefs", "expected"), [
    ({"torrent_content_layout": "Subfolder"}, "Subfolder"),
    ({"torrent_content_layout": "x"}, "Original"),
    ({}, "Original"),
])
def test_content_layout_reads_the_preferences_of_the_instance(prefs, expected):
    mock = _QuiMock()
    mock.preferences = prefs
    assert _adapter(mock).content_layout() == expected


def test_add_torrent_rejects_force_recheck_false():
    adapter = _adapter(_QuiMock())
    with pytest.raises(ValueError):
        adapter.add_torrent("magnet:?xt=...", save_path="/torrents/movie", force_recheck=False)


def test_add_torrent_times_out_if_no_new_hash_appears():
    class _StuckMock(_QuiMock):
        def handler(self, request):
            base = f"/api/instances/{INSTANCE_ID}"
            if request.method == "POST" and request.url.path == f"{base}/torrents":
                return httpx.Response(201)  # accetta ma non aggiunge mai nulla alla lista
            return super().handler(request)

    adapter = _adapter(_StuckMock(), poll_timeout=0.05)
    with pytest.raises(TorrentAddTimeoutError):
        adapter.add_torrent("magnet:?xt=...", save_path="/torrents/movie")


@pytest.mark.parametrize(
    "state,progress,expected",
    [
        ("checkingResumeData", 0.5, "pending"),
        ("error", 0.0, "failed"),
        ("missingFiles", 0.0, "failed"),
        ("uploading", 1.0, "ok"),
        ("stalledDL", 0.4, "failed"),
    ],
)
def test_get_torrent_status_maps_native_state(state, progress, expected):
    mock = _QuiMock(pages=[[{"hash": "h1", "name": "x", "savePath": "/x", "state": state, "progress": progress}]])
    adapter = _adapter(mock)

    status = adapter.get_torrent_status("h1")

    assert status.recheck_status == expected


def test_get_torrent_status_raises_if_not_found():
    adapter = _adapter(_QuiMock())
    with pytest.raises(ValueError):
        adapter.get_torrent_status("missing")


def test_list_torrents_includes_files_and_tracker():
    torrent = {
        "hash": "h1", "name": "Movie.2024.mkv", "savePath": "/torrents/movie",
        "state": "uploading", "category": "movies",
    }
    mock = _QuiMock(
        pages=[[torrent]],
        files_by_hash={"h1": [{"name": "Movie.2024.mkv", "size": 123}, {"name": "Movie.2024.nfo", "size": 10}]},
        trackers_by_hash={"h1": [{"url": "https://tracker.example/announce", "status": 2}]},
    )
    adapter = _adapter(mock)

    torrents = adapter.list_torrents()

    assert len(torrents) == 1
    t = torrents[0]
    assert t.info_hash == "h1"
    assert t.save_path == "/torrents/movie"
    assert t.category == "movies"
    assert t.tracker_url == "https://tracker.example/announce"
    assert [f.path_in_torrent for f in t.files] == ["Movie.2024.mkv", "Movie.2024.nfo"]


def test_list_torrents_treats_empty_category_and_tracker_as_none():
    mock = _QuiMock(pages=[[{"hash": "h1", "name": "x", "savePath": "/x", "state": "uploading"}]])
    adapter = _adapter(mock)

    t = adapter.list_torrents()[0]

    assert t.category is None
    assert t.tracker_url is None


def test_fetch_all_torrents_paginates_until_a_short_page():
    page0 = [{"hash": f"h{i}", "name": "x", "savePath": "/x", "state": "uploading"} for i in range(2)]
    page1 = [{"hash": "h2", "name": "x", "savePath": "/x", "state": "uploading"}]
    mock = _QuiMock(pages=[page0, page1])
    adapter = _adapter(mock, page_limit=2)

    torrents = adapter.list_torrents()

    assert {t.info_hash for t in torrents} == {"h0", "h1", "h2"}


def test_list_torrents_reads_the_qbittorrent_style_save_path():
    """L'istanza qui reale restituisce save_path (nomi qBittorrent), non il
    savePath dello swagger: col solo savePath il path era vuoto per ogni
    torrent e nessun file veniva collegato."""
    from nazgarr.adapters.torrent_client.qui import QuiTorrentClientAdapter

    def handler(request):
        path = request.url.path
        if path.endswith("/files"):
            return httpx.Response(200, json=[{"name": "Movie.mkv", "size": 10}])
        if path.endswith("/trackers"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"torrents": [
            {"hash": "h1", "name": "Movie", "save_path": "/data/torrents/completed/", "state": "uploading"},
        ], "total": 1})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://qui")
    adapter = QuiTorrentClientAdapter(base_url="http://qui", api_token="k", instance_id=1, http_client=client)

    (torrent,) = adapter.list_torrents()
    assert torrent.save_path == "/data/torrents/completed"


def test_add_torrent_waits_for_the_expected_hash():
    mock = _QuiMock(pages=[[{"hash": "other", "name": "o", "state": "uploading", "progress": 1.0}]])
    mock.next_hash = "ABCDEF"
    adapter = _adapter(mock)

    assert adapter.add_torrent("magnet:?xt=...", save_path="/t", expected_info_hash="abcdef") == "ABCDEF"


def test_add_torrent_already_in_the_client_is_a_clear_error():
    from nazgarr.adapters.torrent_client.base import TorrentAlreadyInClientError

    mock = _QuiMock(pages=[[{"hash": "abcdef", "name": "x", "state": "uploading", "progress": 1.0}]])
    adapter = _adapter(mock)

    with pytest.raises(TorrentAlreadyInClientError, match="already in the client"):
        adapter.add_torrent("magnet:?xt=...", save_path="/t", expected_info_hash="ABCDEF")
    assert mock.added_calls == []  # nessuna aggiunta tentata


def test_list_torrents_fetches_details_in_parallel_but_keeps_the_order():
    torrents = [{"hash": f"h{i:02d}", "name": f"t{i}", "save_path": "/data/torrents", "state": "uploading"}
                for i in range(30)]
    mock = _QuiMock(pages=[torrents], files_by_hash={t["hash"]: [{"name": f"{t['name']}.mkv", "size": 1}]
                                                     for t in torrents})
    adapter = _adapter(mock)
    progress = []

    result = adapter.list_torrents(on_progress=lambda done, total: progress.append((done, total)))

    assert [t.info_hash for t in result] == [t["hash"] for t in torrents]
    assert result[7].files[0].path_in_torrent == "t7.mkv"
    assert progress[-1] == (30, 30) and len(progress) == 30


@pytest.mark.parametrize("delete_files", [False, True])
def test_remove_torrent_uses_the_bulk_delete_with_delete_files(delete_files):
    mock = _QuiMock()

    _adapter(mock).remove_torrent("h1", delete_files=delete_files)

    assert mock.bulk_actions == [{"hashes": ["h1"], "action": "delete", "deleteFiles": delete_files}]


def test_the_instances_are_listed_in_qui_order():
    def handler(request: httpx.Request) -> httpx.Response:
        assert (request.url.path, request.headers["X-API-Key"]) == ("/api/instances", "tok123")
        return httpx.Response(200, json=[
            {"id": 3, "name": "seedbox", "host": "http://qb2:8080", "connected": True, "isActive": True,
             "sortOrder": 2},
            {"id": 1, "name": "home", "host": "http://qb1:8080", "connected": True, "isActive": True,
             "sortOrder": 1},
            {"id": 9, "name": "old", "host": "http://qb3", "connected": True, "isActive": False, "sortOrder": 3},
            {"name": "no id"},
        ])

    client = httpx.Client(base_url="http://qui:7476", headers={"X-API-Key": "tok123"},
                          transport=httpx.MockTransport(handler))
    instances = QuiTorrentClientAdapter.list_instances("http://qui:7476", "tok123", http_client=client)

    assert [(i["id"], i["name"], i["active"], i["connected"]) for i in instances] == [
        (1, "home", True, True), (3, "seedbox", True, True), (9, "old", False, False)]


def test_the_api_lists_qui_instances_and_never_sends_a_saved_token_to_a_new_host(client, monkeypatch):
    seen = []
    monkeypatch.setattr(QuiTorrentClientAdapter, "list_instances",
                        staticmethod(lambda base_url, token, http_client=None: seen.append((base_url, token))
                                     or [{"id": 1, "name": "home", "host": None, "active": True, "connected": True}]))
    listed = client.post("/api/torrent-clients/qui-instances", json={"base_url": "http://qui:7476", "api_token": "k"})
    assert listed.json()["instances"][0]["name"] == "home"

    tc = client.post("/api/torrent-clients", json={"label": "qui", "adapter_type": "qui", "base_url": "http://qui:7476",
                                                   "api_token": "saved", "qui_instance_id": 1}).json()["id"]
    client.post("/api/torrent-clients/qui-instances", json={"base_url": "http://qui:7476", "torrent_client_id": tc})
    assert seen[-1] == ("http://qui:7476", "saved")
    moved = client.post("/api/torrent-clients/qui-instances",
                        json={"base_url": "http://evil:1", "torrent_client_id": tc})
    assert moved.status_code == 400 and seen[-1][1] == "saved" and len(seen) == 2
