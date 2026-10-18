"""Adapter rTorrent / ruTorrent contro un httpx.MockTransport che imita
l'XML-RPC di rTorrent (verificato su un'istanza reale, su /RPC2 e sul plugin
httprpc di ruTorrent: tests/integration/test_real_clients.py)."""

import xmlrpc.client
from urllib.parse import parse_qs

import httpx
import pytest
import torf

from nazgarr.adapters.torrent_client.base import TorrentAlreadyInClientError
from nazgarr.adapters.torrent_client.rtorrent import RTorrentAdapter

HASH = "AB" * 20


def _row(**overrides):
    row = {"d.hash": HASH, "d.name": "Movie.mkv", "d.directory": "/downloads", "d.is_multi_file": 0,
           "d.state": 1, "d.is_active": 1, "d.complete": 1, "d.hashing": 0, "d.is_hash_checking": 0,
           "d.custom1": "", "d.ratio": 1500, "d.load_date": 1700000000, "d.timestamp.finished": 0,
           "d.size_bytes": 100, "d.completed_bytes": 100, "d.left_bytes": 0}
    row.update(overrides)
    return row


class _RTorrentMock:
    def __init__(self, rows=None, files=None, trackers=None):
        self.rows = {r["d.hash"]: r for r in rows or []}
        self.files = files or {}
        self.trackers = trackers or {}
        self.calls: list[tuple] = []
        self.forms: list[dict] = []
        self.on_load = HASH
        self.refuse_multicall = False

    def _dispatch(self, method, params):
        if method == "download_list":
            return list(self.rows)
        if method in ("load.raw", "load.normal"):
            self.rows[self.on_load] = _row(**{"d.hash": self.on_load, "d.state": 0, "d.complete": 0})
            return 0
        if method == "d.multicall2":
            return [[r[f.rstrip("=")] for f in params[2:]] for r in self.rows.values()]
        if method == "system.multicall":
            if self.refuse_multicall:
                raise xmlrpc.client.Fault(-32601, "Method not allowed")
            out = []
            for call in params[0]:
                row = self.rows.get(call["params"][0])
                if row is None:
                    out.append({"faultCode": -501, "faultString": "Could not find info-hash."})
                elif call["methodName"] in ("f.multicall", "t.multicall"):
                    out.append([self._dispatch(call["methodName"], call["params"])])
                else:
                    out.append([row[call["methodName"]]])
            return out
        if method == "f.multicall":
            return [[f[c.rstrip("=")] for c in params[2:]] for f in self.files.get(params[0], [])]
        if method == "t.multicall":
            return [[t] for t in self.trackers.get(params[0], [])]
        if method in ("d.is_multi_file", "d.directory"):
            return self.rows[params[0]][method]
        return 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.headers["Content-Type"] == "application/x-www-form-urlencoded":
            self.forms.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
            return httpx.Response(200, json=["", "0", "0"])
        params, method = xmlrpc.client.loads(request.content, use_builtin_types=True)
        self.calls.append((method, params))
        try:
            body = xmlrpc.client.dumps((self._dispatch(method, params),), methodresponse=True, allow_none=True)
        except xmlrpc.client.Fault as fault:
            body = xmlrpc.client.dumps(fault, methodresponse=True)
        return httpx.Response(200, content=body.encode(), headers={"Content-Type": "text/xml"})

    def called(self, method):
        return [p for m, p in self.calls if m == method]


def _adapter(mock, url="http://rt:8000/RPC2", **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(mock.handler))
    return RTorrentAdapter(url, None, None, http_client=client, poll_interval=0.01, **kwargs)


def _torrent_file(tmp_path):
    data = tmp_path / "Movie.mkv"
    data.write_bytes(b"x" * 1000)
    torrent = torf.Torrent(path=data, trackers=["http://t.example/announce"])
    torrent.generate()
    out = tmp_path / "upload.torrent"
    torrent.write(out)
    return out, torrent


def test_a_local_torrent_file_is_sent_by_content_not_by_path(tmp_path):
    path, torrent = _torrent_file(tmp_path)
    mock = _RTorrentMock()
    mock.on_load = torrent.infohash.upper()

    info_hash = _adapter(mock).add_torrent(str(path), save_path="/downloads/my movies, 2024", category="Movies HD")

    target, content, *commands = mock.called("load.raw")[0]
    assert content == path.read_bytes() and target == ""
    assert str(tmp_path) not in repr(mock.calls)
    # La save path così com'è, fra virgolette: la virgola non spezza il comando.
    assert commands == ['d.directory.set="/downloads/my movies, 2024"', 'd.custom1.set="Movies%20HD"']
    assert info_hash == torrent.infohash
    assert [m for m, _ in mock.calls if m.startswith("d.")] == ["d.check_hash", "d.start"]


def test_a_url_stays_a_url_and_the_recheck_always_runs():
    mock = _RTorrentMock()

    _adapter(mock).add_torrent("https://tracker.example/dl/1.torrent", save_path="/d", skip_check_verified=True,
                               tags=["ignored"])

    assert mock.called("load.normal") == [("", "https://tracker.example/dl/1.torrent", 'd.directory.set="/d"')]
    assert not mock.called("load.raw")
    assert mock.called("d.check_hash") == [(HASH,)]  # rTorrent non sa saltarlo
    assert RTorrentAdapter.can_skip_recheck is False


def test_quotes_and_backslashes_in_a_path_are_escaped():
    mock = _RTorrentMock()

    _adapter(mock).add_torrent("magnet:?x", save_path='/d/a "b" \\c')

    assert mock.called("load.normal")[0][2] == 'd.directory.set="/d/a \\"b\\" \\\\c"'


def test_add_rejects_force_recheck_false_and_duplicates(tmp_path):
    path, torrent = _torrent_file(tmp_path)
    mock = _RTorrentMock(rows=[_row(**{"d.hash": torrent.infohash.upper()})])
    adapter = _adapter(mock)
    with pytest.raises(ValueError):
        adapter.add_torrent("magnet:?x", save_path="/d", force_recheck=False)
    with pytest.raises(TorrentAlreadyInClientError):
        adapter.add_torrent("magnet:?x", save_path="/d", expected_info_hash=torrent.infohash)
    # Senza hash atteso: lo calcola dal .torrent (load.raw ignora un duplicato).
    with pytest.raises(TorrentAlreadyInClientError):
        adapter.add_torrent(str(path), save_path="/d")
    assert not mock.called("load.raw")


@pytest.mark.parametrize("fields,state,expected", [
    ({"d.hashing": 3}, "checking", "pending"),
    ({"d.is_hash_checking": 1, "d.complete": 0}, "checking", "pending"),
    ({}, "seeding", "ok"),
    ({"d.state": 0}, "stopped", "ok"),
    ({"d.is_active": 0}, "paused", "ok"),
    ({"d.complete": 0, "d.completed_bytes": 40, "d.left_bytes": 60}, "downloading", "failed"),
])
def test_status_mapping(fields, state, expected):
    mock = _RTorrentMock(rows=[_row(**fields)])

    status = _adapter(mock).get_torrent_status(HASH.lower())

    assert (status.state, status.recheck_status) == (state, expected)
    assert status.incomplete is (expected == "failed")
    assert status.info_hash == HASH.lower()


def test_status_of_an_unknown_torrent_raises():
    with pytest.raises(ValueError):
        _adapter(_RTorrentMock()).get_torrent_status("missing")


def test_info_of_a_multi_file_torrent_is_relative_to_the_folder_that_contains_it():
    mock = _RTorrentMock(
        rows=[_row(**{"d.name": "Show.S01", "d.directory": "/downloads/tv/Show.S01", "d.is_multi_file": 1,
                      "d.custom1": "TV%20Shows", "d.timestamp.finished": 1})],
        files={HASH: [{"f.path": "e1.mkv", "f.size_bytes": 10}, {"f.path": "Extras/s.mkv", "f.size_bytes": 2}]},
        trackers={HASH: ["dht://", "https://t.example/announce"]},
    )
    adapter = _adapter(mock)

    info = adapter.get_torrent_info(HASH.lower())

    assert info.save_path == "/downloads/tv" and info.category == "TV Shows"
    assert [(f.path_in_torrent, f.size_bytes) for f in info.files] == [("Show.S01/e1.mkv", 10),
                                                                       ("Show.S01/Extras/s.mkv", 2)]
    assert info.tracker_url == "https://t.example/announce"
    assert info.ratio == 1.5 and info.added_on == 1700000000 and info.seeding_time_seconds > 0
    assert [t.info_hash for t in adapter.list_torrents()] == [HASH.lower()]
    assert adapter.list_categories() == ["TV Shows"]
    assert adapter.get_torrent_info("cd" * 20) is None


def test_info_of_a_single_file_torrent():
    mock = _RTorrentMock(rows=[_row()], files={HASH: [{"f.path": "Movie.mkv", "f.size_bytes": 100}]})

    info = _adapter(mock).get_torrent_info(HASH)

    assert info.save_path == "/downloads" and [f.path_in_torrent for f in info.files] == ["Movie.mkv"]
    assert info.category is None and info.seeding_time_seconds is None


def test_remove_without_files_only_erases():
    mock = _RTorrentMock(rows=[_row()])

    _adapter(mock).remove_torrent(HASH.lower(), delete_files=False)

    assert [m for m, _ in mock.calls] == ["d.erase"]


def test_remove_with_files_deletes_only_the_torrent_files_then_its_empty_folders():
    mock = _RTorrentMock(
        rows=[_row(**{"d.directory": "/downloads/Show", "d.is_multi_file": 1})],
        files={HASH: [{"f.frozen_path": "/downloads/Show/e1.mkv"}, {"f.frozen_path": "/downloads/Show/Ex/s.mkv"}]},
    )

    _adapter(mock).remove_torrent(HASH, delete_files=True)

    executed = [(m, p[1:]) for m, p in mock.calls if m.startswith("execute")]
    # Prima si leggono i file, poi d.erase, poi la cancellazione.
    assert [m for m, _ in mock.calls[:4]] == ["f.multicall", "d.is_multi_file", "d.directory", "d.erase"]
    assert executed == [
        ("execute.throw", ("rm", "-f", "--", "/downloads/Show/e1.mkv")),
        ("execute.throw", ("rm", "-f", "--", "/downloads/Show/Ex/s.mkv")),
        ("execute.nothrow", ("rmdir", "--", "/downloads/Show/Ex")),
        ("execute.nothrow", ("rmdir", "--", "/downloads/Show")),
    ]


def test_through_rutorrent_files_are_deleted_by_its_erasedata_plugin():
    mock = _RTorrentMock(rows=[_row()])
    adapter = _adapter(mock, url="http://rutorrent:8080")

    adapter.remove_torrent(HASH.lower(), delete_files=True)

    assert adapter.url == "http://rutorrent:8080/plugins/httprpc/action.php"
    assert mock.forms == [{"mode": "removewithdata", "hash": HASH, "v": "1"}]
    assert not mock.called("execute.throw")


def test_endpoint_from_base_url():
    for url, expected in (("http://h/RPC2", "http://h/RPC2"), ("http://h/rutorrent/", "http://h/rutorrent" +
                                                                 "/plugins/httprpc/action.php"),
                          ("http://h/plugins/httprpc/action.php", "http://h/plugins/httprpc/action.php")):
        assert RTorrentAdapter(url, None, None).url == expected


def test_stop_stops_the_torrent():
    mock = _RTorrentMock(rows=[_row()])

    _adapter(mock).stop(HASH.lower())

    assert mock.calls == [("d.stop", (HASH,))]


def _many(count):
    hashes = [f"{i:040X}" for i in range(count)]
    return _RTorrentMock(
        rows=[_row(**{"d.hash": h, "d.name": f"M{i}.mkv"}) for i, h in enumerate(hashes)],
        files={h: [{"f.path": f"M{i}.mkv", "f.size_bytes": i + 1}] for i, h in enumerate(hashes)},
        trackers={h: [f"https://t{i}.example/announce"] for i, h in enumerate(hashes)},
    ), hashes


def test_the_index_asks_files_and_trackers_of_many_torrents_in_one_request():
    """Prima due richieste per torrent (f.multicall e t.multicall): minuti per
    migliaia di torrent dietro il PHP di ruTorrent (audit 2026-10-18)."""
    from nazgarr.adapters.torrent_client import rtorrent

    mock, hashes = _many(rtorrent.DETAIL_BATCH + 5)
    progress = []

    torrents = _adapter(mock).list_torrents(on_progress=lambda done, total: progress.append((done, total)))

    assert [m for m, _ in mock.calls] == ["d.multicall2", "system.multicall", "system.multicall"]
    assert [t.info_hash for t in torrents] == [h.lower() for h in hashes]
    assert [(f.path_in_torrent, f.size_bytes) for f in torrents[7].files] == [("M7.mkv", 8)]
    assert torrents[7].tracker_url == "https://t7.example/announce"
    assert progress == [(rtorrent.DETAIL_BATCH, len(hashes)), (len(hashes), len(hashes))]
    assert _adapter(mock).count_torrents() == len(hashes)


def test_an_endpoint_without_system_multicall_falls_back_to_one_request_per_torrent():
    mock, hashes = _many(3)
    mock.refuse_multicall = True

    torrents = _adapter(mock).list_torrents()

    assert [t.tracker_url for t in torrents] == [f"https://t{i}.example/announce" for i in range(3)]
    assert len(mock.called("f.multicall")) == 3 and len(mock.called("t.multicall")) == 3


def test_a_torrent_gone_during_the_index_fails_it_instead_of_a_partial_list():
    """Un elenco parziale toglierebbe dall'indice torrent che il client ha
    (prune_missing_torrents): un errore su un torrent resta un errore."""
    mock, hashes = _many(2)
    real = mock._dispatch

    def dispatch(method, params):
        if method == "d.multicall2":
            rows = real(method, params)
            del mock.rows[hashes[1]]  # tolto dal client fra l'elenco e i dettagli
            return rows
        return real(method, params)

    mock._dispatch = dispatch
    with pytest.raises(xmlrpc.client.Fault):
        _adapter(mock).list_torrents()
