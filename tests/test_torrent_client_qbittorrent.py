"""Nessuna istanza qBittorrent reale disponibile in fase di sviluppo (vedi
docstring di nazgarr/adapters/torrent_client/qbittorrent.py) — questi test
usano un client fittizio che imita la superficie di qbittorrent-api usata
dall'adapter, non una connessione reale."""

from dataclasses import dataclass

import pytest

from nazgarr.adapters.torrent_client.base import TorrentAddTimeoutError
from nazgarr.adapters.torrent_client.qbittorrent import QBittorrentAdapter


@dataclass
class FakeTorrent:
    hash: str
    name: str = "Movie.2024.mkv"
    save_path: str = "/torrents"
    state: str = "uploading"
    progress: float = 1.0
    category: str = ""
    tracker: str = ""


@dataclass
class FakeFile:
    name: str
    size: int


class FakeQbtClient:
    def __init__(self, torrents=None, files_by_hash=None):
        self._torrents = list(torrents or [])
        self._files_by_hash = files_by_hash or {}
        self.added_calls: list[dict] = []
        self.rechecked: list[str] = []

    def torrents_info(self, torrent_hashes=None):
        if torrent_hashes:
            return [t for t in self._torrents if t.hash == torrent_hashes]
        return list(self._torrents)

    def torrents_files(self, torrent_hash):
        return self._files_by_hash.get(torrent_hash, [])

    def torrents_add(self, save_path, is_skip_checking, use_auto_torrent_management, urls=None, torrent_files=None,
                     category=None, tags=None):
        self.added_calls.append({"urls": urls, "torrent_files": torrent_files, "save_path": save_path,
                                 "is_skip_checking": is_skip_checking,
                                 "category": category, "tags": tags, "auto": use_auto_torrent_management})
        self._torrents.append(FakeTorrent(hash="new-hash", save_path=save_path))

    def torrents_categories(self):
        return {"tv": {"savePath": ""}, "Movie": {"savePath": ""}, "anime": {"savePath": ""}}

    def torrents_recheck(self, torrent_hashes):
        self.rechecked.append(torrent_hashes)


def _adapter(client):
    return QBittorrentAdapter(base_url="http://qbt", username="u", password="p", client=client, poll_interval=0.01)


def test_add_torrent_returns_new_hash_and_forces_recheck():
    client = FakeQbtClient(torrents=[FakeTorrent(hash="existing")])
    adapter = _adapter(client)

    info_hash = adapter.add_torrent("magnet:?xt=...", save_path="/torrents/movie")

    assert info_hash == "new-hash"
    assert client.added_calls[0]["is_skip_checking"] is False
    assert client.rechecked == ["new-hash"]


def test_a_local_torrent_file_is_sent_by_content_not_by_path(tmp_path):
    # Il .torrent di un upload sta nella cartella dati di Nazgarr, che il
    # client non vede: con urls= lo cercherebbe nel suo filesystem.
    torrent = tmp_path / "tracker-1-seed.torrent"
    torrent.write_bytes(b"d4:infod4:name1:xee")
    client = FakeQbtClient()

    _adapter(client).add_torrent(str(torrent), save_path="/downloads/movie")

    assert client.added_calls[0]["torrent_files"] == b"d4:infod4:name1:xee"
    assert client.added_calls[0]["urls"] is None


def test_add_torrent_rejects_force_recheck_false():
    adapter = _adapter(FakeQbtClient())
    with pytest.raises(ValueError):
        adapter.add_torrent("magnet:?xt=...", save_path="/torrents/movie", force_recheck=False)


def test_add_torrent_times_out_if_no_new_hash_appears():
    class StuckClient(FakeQbtClient):
        def torrents_add(self, **kwargs):
            pass  # non aggiunge mai nulla: simula un client che non reagisce

    adapter = QBittorrentAdapter(
        base_url="http://qbt", username="u", password="p", client=StuckClient(), poll_interval=0.01, poll_timeout=0.05
    )
    with pytest.raises(TorrentAddTimeoutError):
        adapter.add_torrent("magnet:?xt=...", save_path="/torrents/movie")


@pytest.mark.parametrize(
    "state,progress,expected",
    [
        ("checkingResumeData", 0.5, "pending"),
        ("error", 0.0, "failed"),
        ("missingFiles", 0.0, "failed"),
        ("uploading", 1.0, "ok"),
        ("stalledDL", 0.4, "failed"),  # progress < 1.0 dopo un presunto recheck = dati incompleti
    ],
)
def test_get_torrent_status_maps_native_state(state, progress, expected):
    client = FakeQbtClient(torrents=[FakeTorrent(hash="h1", state=state, progress=progress)])
    adapter = _adapter(client)

    status = adapter.get_torrent_status("h1")

    assert status.recheck_status == expected


def test_get_torrent_status_raises_if_not_found():
    adapter = _adapter(FakeQbtClient())
    with pytest.raises(ValueError):
        adapter.get_torrent_status("missing")


def test_list_torrents_includes_files_and_tracker():
    client = FakeQbtClient(
        torrents=[FakeTorrent(hash="h1", name="Movie.2024.mkv", save_path="/torrents/movie", category="movies", tracker="https://tracker.example/announce")],
        files_by_hash={"h1": [FakeFile(name="Movie.2024.mkv", size=123), FakeFile(name="Movie.2024.nfo", size=10)]},
    )
    adapter = _adapter(client)

    torrents = adapter.list_torrents()

    assert len(torrents) == 1
    t = torrents[0]
    assert t.info_hash == "h1"
    assert t.category == "movies"
    assert t.tracker_url == "https://tracker.example/announce"
    assert [f.path_in_torrent for f in t.files] == ["Movie.2024.mkv", "Movie.2024.nfo"]


def test_list_torrents_treats_empty_category_and_tracker_as_none():
    client = FakeQbtClient(torrents=[FakeTorrent(hash="h1")], files_by_hash={"h1": []})
    adapter = _adapter(client)

    t = adapter.list_torrents()[0]

    assert t.category is None
    assert t.tracker_url is None


def test_a_torrent_verified_100_percent_by_nazgarr_skips_the_client_recheck_only_on_request():
    client = FakeQbtClient(torrents=[FakeTorrent(hash="existing")])

    _adapter(client).add_torrent("magnet:?xt=...", save_path="/torrents/movie", skip_check_verified=True)

    assert client.added_calls[0]["is_skip_checking"] is True
    assert client.rechecked == []


def test_category_and_tags_are_only_labels():
    client = FakeQbtClient()
    adapter = _adapter(client)

    adapter.add_torrent("magnet:?xt=...", save_path="/torrents/movie", category="movie", tags=["release", "nzg"])

    call = client.added_calls[0]
    # La gestione automatica resta spenta: la categoria non sposta i file.
    assert (call["category"], call["tags"], call["auto"]) == ("movie", "release,nzg", False)
    assert adapter.list_categories() == ["anime", "Movie", "tv"]


@pytest.mark.parametrize("delete_files", [False, True])
def test_remove_torrent_deletes_files_only_on_request(delete_files):
    class DeletingClient(FakeQbtClient):
        def torrents_delete(self, delete_files, torrent_hashes):
            self.deleted = (torrent_hashes, delete_files)

    client = DeletingClient(torrents=[FakeTorrent(hash="h1")])

    _adapter(client).remove_torrent("h1", delete_files=delete_files)

    assert client.deleted == ("h1", delete_files)


def test_close_logs_out_only_when_there_is_a_session():
    """Ogni login apre una sessione nel client (un'ora): chiudendo l'adapter
    si esce, ma uno mai usato non interroga il client."""
    from nazgarr.adapters.torrent_client.qbittorrent import QBittorrentAdapter

    class Client:
        def __init__(self, sid):
            self._SID = sid
            self.logouts = 0

        def auth_log_out(self):
            self.logouts += 1

    used, unused = Client("abc"), Client(None)
    with QBittorrentAdapter("http://qb", "u", "p", client=used):
        pass
    QBittorrentAdapter("http://qb", "u", "p", client=unused).close()
    assert used.logouts == 1 and unused.logouts == 0


def test_the_factory_closes_the_adapter_even_when_the_operation_fails(monkeypatch):
    import pytest

    from nazgarr.integrations import adapter_factory

    closed = []

    class Fake:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(adapter_factory, "build_torrent_client_adapter", lambda row: Fake())
    with pytest.raises(RuntimeError), adapter_factory.torrent_client(object()):
        raise RuntimeError("client irraggiungibile")
    with adapter_factory.torrent_client(object()):
        pass
    assert closed == [True, True]
