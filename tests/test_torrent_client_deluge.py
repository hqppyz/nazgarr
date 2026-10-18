"""Adapter Deluge contro un httpx.MockTransport che imita l'API JSON della
sua Web UI (verificata su un'istanza reale: tests/integration/test_real_clients.py)."""

import base64
import json

import httpx
import pytest

from nazgarr.adapters.torrent_client.base import TorrentAlreadyInClientError
from nazgarr.adapters.torrent_client.deluge import DelugeAdapter


class _DelugeMock:
    def __init__(self, torrents=None, plugins=("Label",), labels=(), connected=True, reads_after_recheck=()):
        self.torrents = dict(torrents or {})
        self.plugins = list(plugins)
        self.labels = list(labels)
        self.connected = connected
        self.logged_in = False
        self.calls: list[tuple[str, list]] = []
        # Le letture di core.get_torrent_status dopo force_recheck, una alla
        # volta, prima di quella in self.torrents: lo stato che Deluge
        # aggiorna solo all'evento dopo.
        self.reads_after_recheck = list(reads_after_recheck)
        self.rechecked = False

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
        if method == "core.force_recheck":
            self.rechecked = True
            return ok(True)
        if method == "core.get_torrent_status":
            if self.rechecked and self.reads_after_recheck:
                return ok({**self.reads_after_recheck.pop(0), "hash": params[0]})
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


# is_auto_managed è sempre vero, come lo riporta Deluge: è l'opzione salvata,
# non lo stato di libtorrent, e la mappatura non la guarda (audit 2026-10-18).
@pytest.mark.parametrize("state,progress,paused,expected", [
    ("Checking", 40.0, False, "pending"),
    # Subito dopo force_recheck, visto sull'istanza reale: in coda per il controllo.
    ("Seeding", 0.0, True, "pending"),
    ("Queued", 0.0, True, "pending"),
    # force_recheck l'ha avviato per il controllo, lo stato di Deluge non l'ha ancora visto.
    ("Paused", 0.0, False, "pending"),
    ("Seeding", 100.0, False, "ok"),
    ("Paused", 100.0, True, "ok"),
    ("Downloading", 30.0, False, "failed"),
    # Un reseed fermo dopo un recheck fallito: force_recheck l'ha rimesso in
    # pausa. Prima era "pending" per sempre: il seed job non finiva mai.
    ("Paused", 30.0, True, "failed"),
    # La stessa lettura subito dopo l'aggiunta in pausa, se Deluge non ha
    # ancora tolto la pausa: add_torrent aspetta che passi (test sotto).
    ("Paused", 0.0, True, "failed"),
    ("Error", 0.0, False, "failed"),
])
def test_status_mapping(state, progress, paused, expected):
    mock = _DelugeMock(torrents={"h1": {"state": state, "progress": progress, "paused": paused,
                                        "is_auto_managed": True, "total_wanted": 100, "total_done": 30}})

    status = _adapter(mock).get_torrent_status("h1")

    assert status.recheck_status == expected
    assert status.progress == pytest.approx(progress / 100)
    assert status.incomplete is (expected == "failed" and state != "Error")
    assert status.amount_left == 70
    assert "is_auto_managed" not in mock.called("core.get_torrent_status")[-1][1]


PAUSED_UNCHECKED = {"state": "Paused", "progress": 0.0, "paused": True}


def test_a_paused_add_returns_once_deluge_shows_its_check():
    # Fra force_recheck e l'evento che Deluge elabora dopo, la lettura è
    # quella di un recheck fallito: un reconcile lì chiudeva il seed job.
    mock = _DelugeMock(reads_after_recheck=[PAUSED_UNCHECKED, PAUSED_UNCHECKED])
    adapter = _adapter(mock)

    info_hash = adapter.add_torrent("magnet:?x", save_path="/d", stopped=True)

    assert len(mock.called("core.get_torrent_status")) == 3  # due "Paused", poi "Checking"
    assert adapter.get_torrent_status(info_hash).recheck_status == "pending"


def test_the_wait_after_a_paused_add_is_bounded(monkeypatch):
    # Un controllo fallito già finito alla prima lettura (un torrent piccolo):
    # la lettura resta "Paused", e dopo l'attesa è l'esito giusto.
    from nazgarr.adapters.torrent_client import deluge

    monkeypatch.setattr(deluge, "CHECK_START_TIMEOUT", 0.05)
    mock = _DelugeMock(reads_after_recheck=[PAUSED_UNCHECKED] * 1000)
    adapter = _adapter(mock)

    info_hash = adapter.add_torrent("magnet:?x", save_path="/d", stopped=True)

    assert adapter.get_torrent_status(info_hash).recheck_status == "failed"
    assert len(mock.reads_after_recheck) > 900


def test_a_running_add_and_a_running_recheck_do_not_wait():
    mock = _DelugeMock(reads_after_recheck=[{"state": "Seeding", "progress": 0.0, "paused": False}] * 5)
    adapter = _adapter(mock)

    adapter.add_torrent("magnet:?x", save_path="/d")
    assert mock.called("core.get_torrent_status") == []
    adapter.recheck("abc123")
    assert len(mock.called("core.get_torrent_status")) == 1


def test_the_recheck_of_a_paused_torrent_waits_like_the_add():
    # Il retry di un reseed fallito, fermo: lo si ricontrolla.
    mock = _DelugeMock(torrents={"abc123": {"state": "Checking", "progress": 5.0, "paused": False}},
                       reads_after_recheck=[PAUSED_UNCHECKED])
    adapter = _adapter(mock)

    adapter.recheck("ABC123")

    assert mock.called("core.force_recheck") == [[["abc123"]]]
    assert len(mock.called("core.get_torrent_status")) == 2


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


def test_stop_pauses_the_torrent():
    mock = _DelugeMock()

    _adapter(mock).stop("H1")

    assert mock.called("core.pause_torrent") == [[["h1"]]]


def test_a_reseed_is_added_paused_and_rechecked_then_resumed_on_request():
    # Decisione dell'utente, 2026-10-18: force_recheck di Deluge controlla
    # anche un torrent in pausa e lo rimette in pausa dopo.
    mock = _DelugeMock()
    adapter = _adapter(mock)

    adapter.add_torrent("magnet:?x", save_path="/d", stopped=True)

    assert DelugeAdapter.can_add_stopped is True
    assert mock.called("core.add_torrent_magnet")[0][1]["add_paused"] is True
    assert mock.called("core.force_recheck") == [[["abc123"]]] and not mock.called("core.resume_torrent")
    adapter.start("ABC123")
    assert mock.called("core.resume_torrent") == [[["abc123"]]]


def test_the_live_path_check_asks_only_save_path_and_files():
    mock = _DelugeMock(torrents={
        "h1": {"name": "M", "save_path": "/d/", "state": "Seeding",
               "files": [{"path": "M/a.nfo", "size": 1}, {"path": "M/a.mkv", "size": 9}]},
        "h2": {"name": "N", "save_path": "/d", "state": "Seeding", "files": []},
    })

    largest = _adapter(mock).list_largest_files(limit=5)

    assert mock.called("core.get_torrents_status")[-1] == [{}, ["hash", "name", "save_path", "state", "files"]]
    assert [(t.info_hash, t.save_path, [f.path_in_torrent for f in t.files]) for t in largest] == [
        ("h1", "/d", ["M/a.mkv"]), ("h2", "/d", [])]
