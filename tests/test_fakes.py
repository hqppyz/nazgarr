"""I finti comuni (tests/fakes.py) restano fedeli al contratto degli
adapter: un parametro nuovo di add_torrent, o uno cambiato, fa fallire
questo test invece di lasciare verdi test che un adapter vero romperebbe
(audit 2026-10-18)."""

import inspect

import pytest

from nazgarr.adapters.torrent_client.base import (
    TorrentClientAdapter,
    TorrentStatus,
    layout_kwargs,
    stopped_kwargs,
)
from tests.fakes import RecordingClient


def test_the_recording_client_has_the_contract_signature():
    def parameters(method):
        return [(p.name, p.default, p.kind) for p in inspect.signature(method).parameters.values()]

    assert parameters(RecordingClient.add_torrent) == parameters(TorrentClientAdapter.add_torrent)
    assert issubclass(RecordingClient, TorrentClientAdapter)
    client = RecordingClient()
    # Le stesse strade dell'esecutore di un adapter incluso.
    assert layout_kwargs(client, "Subfolder") == {"content_layout": "Subfolder"}
    assert stopped_kwargs(client) == {"stopped": True}


def test_it_records_every_add_and_never_accepts_a_skipped_recheck(tmp_path):
    torrent = tmp_path / "x.torrent"
    torrent.write_bytes(b"not really a torrent")
    client = RecordingClient()

    info_hash = client.add_torrent(str(torrent), "/seed", expected_info_hash="ABC", stopped=True, category="tv")

    assert info_hash == "abc"
    (added,) = client.added
    assert (added.content, added.save_path) == (b"not really a torrent", "/seed")
    assert added.options["stopped"] is True and added.options["category"] == "tv"
    with pytest.raises(ValueError):
        client.add_torrent(str(torrent), "/seed", force_recheck=False)


def test_its_answers_and_failures_can_be_set():
    client = RecordingClient(info_hash="h", add_error=RuntimeError("client down"),
                             status=TorrentStatus("h", "uploading", "ok", 1.0))
    with pytest.raises(RuntimeError):
        client.add_torrent("https://t.example/download/1", "/seed")
    assert client.added[0].content is None  # un URL resta un URL
    assert client.get_torrent_status("h").recheck_status == "ok"
    assert RecordingClient().get_torrent_status("x").recheck_status == "pending"
    client.start("h")
    client.stop("h")
    client.recheck("h")
    assert (client.started, client.stopped, client.rechecked) == (["h"], ["h"], ["h"])
