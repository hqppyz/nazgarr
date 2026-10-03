"""Adapter Deluge contro un httpx.MockTransport che imita l'API JSON della
sua Web UI (verificata su un'istanza reale: tests/integration/test_real_clients.py)."""

import base64
import json

import httpx
import pytest

from nazgarr.adapters.torrent_client.base import TorrentAlreadyInClientError
from nazgarr.adapters.torrent_client.deluge import DelugeAdapter


class _DelugeMock:
    def __init__(self, torrents=None, plugins=("Label",), labels=(), connected=True):
        self.torrents = dict(torrents or {})
        self.plugins = list(plugins)
        self.labels = list(labels)
        self.connected = connected
        self.logged_in = False
        self.calls: list[tuple[str, list]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/json"
        body = json.loads(request.content)
        method, params = body["method"], body["params"]
        self.calls.append((method, params))

        def ok(result):
            return httpx.Response(200, json={"result": result, "error": None, "id": body["id"]})

        if method == "auth.login":
            self.logged_in = params == ["pw"]
            return ok(self.logged_in)
        if not self.logged_in:
            return httpx.Response(200, json={"result": None, "error": {"message": "Not authenticated", "code": 1},
                                             "id": body["id"]})
        if method == "web.connected":
            return ok(self.connected)
        if method == "web.get_hosts":
            return ok([["host-1", "127.0.0.1", 58846, "localclient"]])
        if method == "web.connect":
            self.connected = True
            return ok([])
        if method == "core.get_torrents_status":
            return ok({h: {**t, "hash": h} for h, t in self.torrents.items()})
        if method == "core.get_torrent_status":
            torrent = self.torrents.get(params[0])
            return ok({**torrent, "hash": params[0]} if torrent else {})
        if method in ("core.add_torrent_file", "core.add_torrent_url", "core.add_torrent_magnet"):
            self.torrents["abc123"] = {"state": "Checking", "progress": 0.0}
            return ok("abc123")
        if method == "core.get_enabled_plugins":
            return ok(self.plugins)
        if method == "label.get_labels":
            return ok(self.labels)
        if method == "label.add":
            self.labels.append(params[0])
            return ok(None)
        return ok(True)

    def called(self, method):
        return [p for m, p in self.calls if m == method]


def _adapter(mock, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(mock.handler))
    return DelugeAdapter("http://deluge:8112", "pw", http_client=client, poll_interval=0.01, **kwargs)


def test_a_local_torrent_file_is_sent_by_content_not_by_path(tmp_path):
    torrent = tmp_path / "upload.torrent"
    torrent.write_bytes(b"d4:infod4:name1:xee")
    mock = _DelugeMock()

    info_hash = _adapter(mock).add_torrent(str(torrent), save_path="/downloads/movies")

    name, content, options = mock.called("core.add_torrent_file")[0]
    assert base64.b64decode(content) == b"d4:infod4:name1:xee"
    assert name == "upload.torrent" and str(tmp_path) not in json.dumps(mock.calls)
    assert options == {"download_location": "/downloads/movies", "add_paused": False, "seed_mode": False}
    assert info_hash == "abc123"
    assert mock.called("core.force_recheck") == [[["abc123"]]]


def test_a_url_stays_a_url():
    mock = _DelugeMock()
    adapter = _adapter(mock)

    adapter.add_torrent("https://tracker.example/dl/1.torrent", save_path="/d")
    del mock.torrents["abc123"]
    adapter.add_torrent("magnet:?xt=urn:btih:abc", save_path="/d")

    assert mock.called("core.add_torrent_url")[0][0] == "https://tracker.example/dl/1.torrent"
    assert mock.called("core.add_torrent_magnet")[0][0] == "magnet:?xt=urn:btih:abc"
    assert not mock.called("core.add_torrent_file")


def test_skip_check_verified_uses_seed_mode_and_no_recheck():
    mock = _DelugeMock()

    _adapter(mock).add_torrent("magnet:?x", save_path="/d", skip_check_verified=True)

    assert mock.called("core.add_torrent_magnet")[0][1]["seed_mode"] is True
    assert mock.called("core.force_recheck") == []


def test_the_web_ui_is_connected_to_its_daemon_when_it_is_not():
    mock = _DelugeMock(connected=False)

    _adapter(mock).list_torrents()

    assert mock.called("web.connect") == [["host-1"]]


def test_a_wrong_password_is_an_error():
    from nazgarr.adapters.torrent_client.deluge import DelugeError

    client = httpx.Client(transport=httpx.MockTransport(_DelugeMock().handler))
    with pytest.raises(DelugeError):
        DelugeAdapter("http://deluge:8112", "wrong", http_client=client).list_torrents()


def test_category_is_a_label_created_if_missing_and_tags_are_ignored():
    mock = _DelugeMock(labels=["tv"])
    adapter = _adapter(mock)

    adapter.add_torrent("magnet:?x", save_path="/d", category="Movies", tags=["upload"])

    assert mock.called("label.add") == [["movies"]]
    assert mock.called("label.set_torrent") == [["abc123", "movies"]]
    assert adapter.list_categories() == ["movies", "tv"]


def test_without_the_label_plugin_there_are_no_categories():
    mock = _DelugeMock(plugins=[])
    adapter = _adapter(mock)

    adapter.add_torrent("magnet:?x", save_path="/d", category="movies")

    assert mock.called("label.set_torrent") == []
    assert adapter.list_categories() == []


def test_add_rejects_force_recheck_false_and_duplicates():
    mock = _DelugeMock(torrents={"abc123": {"state": "Seeding"}})
    adapter = _adapter(mock)
    with pytest.raises(ValueError):
        adapter.add_torrent("magnet:?x", save_path="/d", force_recheck=False)
    with pytest.raises(TorrentAlreadyInClientError):
        adapter.add_torrent("magnet:?x", save_path="/d", expected_info_hash="ABC123")


@pytest.mark.parametrize("state,progress,paused,auto,expected", [
    ("Checking", 40.0, False, True, "pending"),
    # Subito dopo force_recheck, visto sull'istanza reale: in coda per il controllo.
    ("Seeding", 0.0, True, True, "pending"),
    ("Queued", 0.0, True, True, "pending"),
    ("Seeding", 100.0, False, True, "ok"),
    ("Paused", 100.0, True, False, "ok"),
    ("Downloading", 30.0, False, True, "failed"),
    ("Paused", 30.0, True, False, "failed"),
    ("Error", 0.0, False, True, "failed"),
])
def test_status_mapping(state, progress, paused, auto, expected):
    mock = _DelugeMock(torrents={"h1": {"state": state, "progress": progress, "paused": paused,
                                        "is_auto_managed": auto, "total_wanted": 100, "total_done": 30}})

    status = _adapter(mock).get_torrent_status("h1")

    assert status.recheck_status == expected
    assert status.progress == pytest.approx(progress / 100)
    assert status.incomplete is (expected == "failed" and state != "Error")
    assert status.amount_left == 70


def test_status_of_an_unknown_torrent_raises():
    with pytest.raises(ValueError):
        _adapter(_DelugeMock()).get_torrent_status("missing")


def test_info_and_list():
    mock = _DelugeMock(torrents={"h1": {
        "name": "Show.S01", "save_path": "/downloads/tv/", "state": "Seeding", "label": "tv",
        "trackers": [{"url": "https://t.example/announce", "tier": 0}],
        "files": [{"path": "Show.S01/e1.mkv", "size": 10}, {"path": "Show.S01/e2.mkv", "size": 20}],
        "ratio": 1.5, "seeding_time": 60, "time_added": 1700000000.5,
    }})
    adapter = _adapter(mock)

    info = adapter.get_torrent_info("h1")
    listed = adapter.list_torrents()

    assert info.save_path == "/downloads/tv" and info.category == "tv" and info.state == "Seeding"
    assert [(f.path_in_torrent, f.size_bytes) for f in info.files] == [("Show.S01/e1.mkv", 10), ("Show.S01/e2.mkv", 20)]
    assert info.tracker_url == "https://t.example/announce"
    assert (info.ratio, info.seeding_time_seconds, info.added_on) == (1.5, 60, 1700000000)
    assert [t.info_hash for t in listed] == ["h1"]
    assert adapter.get_torrent_info("other") is None


@pytest.mark.parametrize("delete_files", [False, True])
def test_remove_torrent(delete_files):
    mock = _DelugeMock()

    _adapter(mock).remove_torrent("H1", delete_files=delete_files)

    assert mock.called("core.remove_torrent") == [["h1", delete_files]]
