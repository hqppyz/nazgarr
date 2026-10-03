"""Adapter Transmission contro un httpx.MockTransport che imita la sua RPC
(verificata su un'istanza reale: tests/integration/test_real_clients.py)."""

import base64
import json

import httpx
import pytest

from nazgarr.adapters.torrent_client.base import TorrentAlreadyInClientError
from nazgarr.adapters.torrent_client.transmission import TransmissionAdapter


class _TransmissionMock:
    def __init__(self, torrents=None):
        self.torrents = list(torrents or [])
        self.calls: list[dict] = []
        self.session = "sid-1"

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/transmission/rpc"
        if request.headers.get("X-Transmission-Session-Id") != self.session:
            return httpx.Response(409, headers={"X-Transmission-Session-Id": self.session})
        body = json.loads(request.content)
        self.calls.append(body)
        method, args = body["method"], body.get("arguments") or {}
        if method == "torrent-get":
            ids = args.get("ids")
            found = [t for t in self.torrents if ids is None or t["hashString"] in ids]
            return httpx.Response(200, json={"result": "success", "arguments": {"torrents": found}})
        if method == "torrent-add":
            new = {"hashString": "abc123", "name": "x", "downloadDir": args["download-dir"], "status": 0, "error": 0,
                   "percentDone": 0.0, "leftUntilDone": 10, "labels": [], "trackers": [], "files": []}
            self.torrents.append(new)
            return httpx.Response(200, json={"result": "success",
                                             "arguments": {"torrent-added": {"hashString": "abc123", "id": 1}}})
        return httpx.Response(200, json={"result": "success", "arguments": {}})

    def methods(self):
        return [c["method"] for c in self.calls if c["method"] != "torrent-get"]


def _adapter(mock, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(mock.handler))
    return TransmissionAdapter("http://tr:9091", "u", "p", http_client=client, poll_interval=0.01, **kwargs)


def test_a_local_torrent_file_is_sent_by_content_not_by_path(tmp_path):
    torrent = tmp_path / "upload.torrent"
    torrent.write_bytes(b"d4:infod4:name1:xee")
    mock = _TransmissionMock()

    info_hash = _adapter(mock).add_torrent(str(torrent), save_path="/downloads/movies")

    add = next(c["arguments"] for c in mock.calls if c["method"] == "torrent-add")
    assert base64.b64decode(add["metainfo"]) == b"d4:infod4:name1:xee"
    assert "filename" not in add
    assert add["download-dir"] == "/downloads/movies"  # così com'è
    assert info_hash == "abc123"


def test_a_url_stays_a_url_and_the_recheck_always_runs():
    mock = _TransmissionMock()

    _adapter(mock).add_torrent("https://tracker.example/dl/1.torrent", save_path="/d", skip_check_verified=True)

    add = next(c["arguments"] for c in mock.calls if c["method"] == "torrent-add")
    assert add["filename"] == "https://tracker.example/dl/1.torrent" and "metainfo" not in add
    # Transmission non sa saltare il controllo: lo fa comunque.
    assert mock.methods() == ["torrent-add", "torrent-verify"]
    assert TransmissionAdapter.can_skip_recheck is False


def test_labels_carry_category_and_tags():
    mock = _TransmissionMock()
    adapter = _adapter(mock)

    adapter.add_torrent("magnet:?xt=urn:btih:abc", save_path="/d", category="movies", tags=["upload", "movies"])

    labels = next(c["arguments"] for c in mock.calls if c["method"] == "torrent-set")
    assert labels == {"ids": ["abc123"], "labels": ["movies", "upload"]}
    assert adapter.list_categories() == []


def test_add_rejects_force_recheck_false_and_duplicates():
    mock = _TransmissionMock(torrents=[{"hashString": "abc123"}])
    adapter = _adapter(mock)
    with pytest.raises(ValueError):
        adapter.add_torrent("magnet:?x", save_path="/d", force_recheck=False)
    with pytest.raises(TorrentAlreadyInClientError):
        adapter.add_torrent("magnet:?x", save_path="/d", expected_info_hash="ABC123")


def test_a_duplicate_reported_by_transmission_is_not_a_timeout():
    class Duplicate(_TransmissionMock):
        def handler(self, request):
            if request.headers.get("X-Transmission-Session-Id") == self.session:
                body = json.loads(request.content)
                if body["method"] == "torrent-add":
                    return httpx.Response(200, json={"result": "success", "arguments": {
                        "torrent-duplicate": {"hashString": "abc123"}}})
            return super().handler(request)

    with pytest.raises(TorrentAlreadyInClientError):
        _adapter(Duplicate()).add_torrent("magnet:?x", save_path="/d")


@pytest.mark.parametrize("status,error,done,expected,incomplete", [
    (2, 0, 0.5, "pending", False),
    (1, 0, 0.0, "pending", False),
    (6, 0, 1.0, "ok", False),
    (0, 0, 1.0, "ok", False),
    (4, 0, 0.4, "failed", True),
    (0, 3, 0.0, "failed", False),  # errore locale: dati mancanti
    (6, 2, 1.0, "ok", False),  # errore del tracker: i dati sono a posto
])
def test_status_mapping(status, error, done, expected, incomplete):
    mock = _TransmissionMock(torrents=[{"hashString": "h1", "status": status, "error": error,
                                        "percentDone": done, "leftUntilDone": 5}])

    result = _adapter(mock).get_torrent_status("H1".lower())

    assert (result.recheck_status, result.incomplete, result.amount_left) == (expected, incomplete, 5)


def test_status_of_an_unknown_torrent_raises():
    with pytest.raises(ValueError):
        _adapter(_TransmissionMock()).get_torrent_status("missing")


def test_info_and_list():
    mock = _TransmissionMock(torrents=[{
        "hashString": "h1", "name": "Show.S01", "downloadDir": "/downloads/tv/", "status": 0, "error": 0,
        "labels": ["tv"], "trackers": [{"announce": "https://t.example/announce"}],
        "files": [{"name": "Show.S01/e1.mkv", "length": 10}, {"name": "Show.S01/e2.mkv", "length": 20}],
        "uploadRatio": -1, "secondsSeeding": 30, "addedDate": 1700000000,
    }])
    adapter = _adapter(mock)

    info = adapter.get_torrent_info("h1")
    progress = []
    listed = adapter.list_torrents(on_progress=lambda done, total: progress.append((done, total)))

    assert info.save_path == "/downloads/tv" and info.state == "stopped"
    assert [(f.path_in_torrent, f.size_bytes) for f in info.files] == [("Show.S01/e1.mkv", 10), ("Show.S01/e2.mkv", 20)]
    assert info.tracker_url == "https://t.example/announce" and info.category is None
    assert (info.ratio, info.seeding_time_seconds, info.added_on) == (None, 30, 1700000000)
    assert [t.info_hash for t in listed] == ["h1"] and progress == [(1, 1)]
    assert adapter.get_torrent_info("other") is None


@pytest.mark.parametrize("delete_files", [False, True])
def test_remove_torrent(delete_files):
    mock = _TransmissionMock()

    _adapter(mock).remove_torrent("H1", delete_files=delete_files)

    assert mock.calls[-1] == {"method": "torrent-remove",
                              "arguments": {"ids": ["h1"], "delete-local-data": delete_files}}


def test_rpc_url_from_base_url():
    assert TransmissionAdapter("http://tr:9091/", None, None).url == "http://tr:9091/transmission/rpc"
    assert TransmissionAdapter("http://h/custom/rpc", None, None).url == "http://h/custom/rpc"
