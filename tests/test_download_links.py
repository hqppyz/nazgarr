"""Il link di download di un candidato senza la chiave del tracker nel DB
(nazgarr/reseed/download_links.py, audit 2026-10-18): la chiave torna solo
quando il .torrent si scarica, dall'adapter del tracker."""

from contextlib import contextmanager

import pytest

from nazgarr.adapters.tracker.base import TorrentCandidate, Unit3dTrackerAdapter, UploadError
from nazgarr.core.models import Candidate, Tracker
from nazgarr.reseed import download_links, executor, full_check

KEYED = "https://t.example/torrent/download/42.secretkey123"
STORED = "https://t.example/torrent/download/42.rsskey"


class _Tracker:
    """Un adapter UNIT3D finto: rewrite_download_link come quello vero."""

    def __init__(self, rss_key=None, fail=(), detail_link=None):
        self.rss_key = rss_key
        self.fail = set(fail)
        self.detail_link = detail_link
        self.links = []
        self.details = 0

    def rewrite_download_link(self, url):
        return Unit3dTrackerAdapter.rewrite_download_link(self, url)

    _DOWNLOAD_KEY_RE = Unit3dTrackerAdapter._DOWNLOAD_KEY_RE
    base_url = "https://t.example"

    def get_torrent_detail(self, torrent_id_remote):
        self.details += 1
        return TorrentCandidate(torrent_id_remote=torrent_id_remote, info_hash=None, name="x", size_bytes=1,
                                file_list=None, mediainfo_unique_id=None, download_link=self.detail_link)

    def download_torrent(self, url):
        self.links.append(url)
        if url in self.fail:
            raise UploadError("rejected")
        return b"torrent-bytes"


def _candidate(link=STORED):
    return Candidate(tracker=Tracker(label="t", adapter_type="unit3d", base_url="https://t.example"),
                     torrent_id_remote="42", download_link=link)


def test_the_key_is_never_stored():
    assert download_links.stored_link(_Tracker(), KEYED) == STORED
    assert download_links.strip_key("https://t.example/torrents/12") == "https://t.example/torrents/12"

    class Plugin:  # un adapter che non sa rimettere la chiave: il link resta com'è
        pass

    assert download_links.stored_link(Plugin(), KEYED) == KEYED


def test_the_current_key_is_put_back_when_downloading():
    tracker = _Tracker(rss_key="currentkey")

    assert download_links.download(tracker, _candidate()) == b"torrent-bytes"
    assert tracker.links == ["https://t.example/torrent/download/42.currentkey"]
    assert tracker.details == 0


def test_without_a_known_key_the_link_comes_from_the_torrent_detail():
    tracker = _Tracker(rss_key=None, detail_link=KEYED)

    download_links.download(tracker, _candidate())

    assert tracker.links == [KEYED] and tracker.details == 1


def test_a_rotated_key_is_retried_with_the_detail_link():
    old = "https://t.example/torrent/download/42.oldkey"
    tracker = _Tracker(rss_key="oldkey", fail={old}, detail_link=KEYED)

    download_links.download(tracker, _candidate())

    assert tracker.links == [old, KEYED]


def test_no_key_and_no_detail_is_a_clear_error():
    with pytest.raises(UploadError, match="No download key"):
        download_links.download(_Tracker(rss_key=None, detail_link=None), _candidate())


def test_a_link_stored_before_the_change_is_used_as_it_is():
    tracker = _Tracker(rss_key="currentkey")

    download_links.download(tracker, _candidate(KEYED))

    assert tracker.links == [KEYED]


@contextmanager
def _adapter(fake):
    yield fake


def test_the_executor_and_the_full_check_download_with_the_key_put_back(monkeypatch):
    from nazgarr.integrations import adapter_factory

    real_executor = executor.__dict__["_download_torrent"]
    tracker = _Tracker(rss_key="currentkey")
    monkeypatch.setattr(adapter_factory, "tracker", lambda row: _adapter(tracker))

    assert real_executor(_candidate()) == b"torrent-bytes"
    assert full_check._download_torrent(_candidate()) == b"torrent-bytes"
    assert tracker.links == ["https://t.example/torrent/download/42.currentkey"] * 2
