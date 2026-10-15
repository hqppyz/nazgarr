"""Fallback sul contenuto per i season pack (issue #25,
nazgarr/torrents/layout.py): un video che né la history né il nome
abbinano si cerca fra gli episodi della serie con la stessa size, e si
accetta solo se i piece hash del .torrent lo confermano. Filesystem vero in
tmp_path, nessuna chiamata di rete."""

import hashlib
from datetime import UTC, datetime

from nazgarr.adapters.tracker.base import TorrentCandidate
from nazgarr.core.models import Candidate, MatchReview, MediaFile
from nazgarr.reseed import matching
from nazgarr.torrents import layout as torrent_layout
from tests.test_season_pack import E01, E02, PIECE, _bencode, _library, _no_mediainfo

FOLDER = "Show.S01.ITA.1080p-GRP"
# Nomi da cui guessit non ricava stagione ed episodio.
RENAMED = {
    "Show - S01 - 01 - La nostra famiglia.mkv": E01,
    "Show - S01 - 02 - Il secondo episodio.mkv": E02,
}


def _torrent(files: dict[str, bytes]) -> bytes:
    stream = b"".join(files.values())
    pieces = b"".join(hashlib.sha1(stream[i : i + PIECE]).digest() for i in range(0, len(stream), PIECE))
    return _bencode({"info": {
        "name": FOLDER, "piece length": PIECE, "pieces": pieces,
        "files": [{"length": len(c), "path": [n]} for n, c in files.items()],
    }})


class Tracker:
    def __init__(self, files: dict[str, bytes] = RENAMED, torrent_id="901"):
        self.files = files
        self.torrent_id = torrent_id
        self.downloads = []

    def search_by_tmdb(self, tmdb_id):
        return [TorrentCandidate(
            torrent_id_remote=self.torrent_id, info_hash=None, name="Show S01 ITA",
            size_bytes=sum(map(len, self.files.values())), file_list=list(self.files), mediainfo_unique_id=None,
            folder=FOLDER, download_link=f"https://t.example/torrent/download/{self.torrent_id}.pk",
            file_sizes={n: len(c) for n, c in self.files.items()},
        )]

    def download_torrent(self, url):
        self.downloads.append(url)
        return _torrent(self.files)


def _add_episode_file(db_session, disk, of: MediaFile, name: str, inode: int) -> MediaFile:
    """Un secondo file in libreria dello stesso episodio di `of` (una copia
    o un hardlink), con lo stesso contenuto."""
    folder = disk.root_path + "/media/tv/Show/Season 01"
    with open(f"{folder}/{of.relative_path.rsplit('/', 1)[1]}", "rb") as src, open(f"{folder}/{name}", "wb") as fh:
        fh.write(src.read())
    mf = MediaFile(disk_id=disk.id, relative_path=f"media/tv/Show/Season 01/{name}", size_bytes=of.size_bytes,
                   st_dev=1, inode=inode, media_item_id=of.media_item_id, last_scan_id=of.last_scan_id,
                   last_seen_at=datetime.now(UTC))
    db_session.add(mf)
    db_session.commit()
    return mf


def test_renamed_episodes_are_found_by_their_content(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, e02) = _library(db_session, tmp_path, with_srt=False)
    adapter = Tracker()

    matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    (candidate,) = db_session.query(Candidate).all()
    assert candidate.confidence == matching.CONFIDENCE_PIECE_VERIFIED
    assert candidate.ambiguity_reason is None
    # E01 ed E02 hanno la stessa size: ognuno è stato riconosciuto dai suoi piece.
    by_path = {f.torrent_path: f for f in candidate.files}
    assert by_path["Show - S01 - 01 - La nostra famiglia.mkv"].media_file_id == e01.id
    assert by_path["Show - S01 - 02 - Il secondo episodio.mkv"].media_file_id == e02.id
    assert {f.match_method for f in candidate.files} == {"content"}
    assert all(f.piece_verified for f in candidate.files)
    assert len(adapter.downloads) == 1
    assert db_session.query(MatchReview).count() == 1


def test_names_and_history_still_come_first(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, e02) = _library(db_session, tmp_path, with_srt=False)
    files = {"Show.S01E01.1080p-GRP.mkv": E01, "Show - S01 - 02 - Il secondo episodio.mkv": E02}

    matching.run_media_to_torrent_matching(db_session, tracker, Tracker(files))

    (candidate,) = db_session.query(Candidate).all()
    assert candidate.confidence == matching.CONFIDENCE_PIECE_VERIFIED
    assert {f.media_file_id: f.match_method for f in candidate.files} == {e01.id: "name", e02.id: "content"}


def test_same_size_but_different_content_stays_missing(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _files = _library(db_session, tmp_path, with_srt=False)
    other = b"another-episode!" * 4  # stessa size di E02, altri byte
    files = {"Show - S01 - 01 - La nostra famiglia.mkv": E01, "Show - S01 - 02 - Il secondo episodio.mkv": other}

    matching.run_media_to_torrent_matching(db_session, tracker, Tracker(files))

    (candidate,) = db_session.query(Candidate).all()
    assert candidate.ambiguity_reason == "season_pack_partial"
    assert candidate.confidence == matching.CONFIDENCE_NO_MATCH
    assert db_session.query(MatchReview).count() == 0


def test_two_different_files_with_the_same_content_are_inconclusive(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    disk, tracker, (e01, _e02) = _library(db_session, tmp_path, with_srt=False)
    _add_episode_file(db_session, disk, e01, "Show - S01E01 - Pilot (copy).mkv", inode=60)

    matching.run_media_to_torrent_matching(db_session, tracker, Tracker())

    (candidate,) = db_session.query(Candidate).all()
    assert candidate.ambiguity_reason == "season_pack_partial"
    first = next(f for f in candidate.files if "01 - La nostra" in f.torrent_path)
    assert first.media_file_id is None


def test_a_hardlink_of_the_same_episode_is_the_same_file(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    disk, tracker, (e01, _e02) = _library(db_session, tmp_path, with_srt=False)
    _add_episode_file(db_session, disk, e01, "Show - S01E01 - Pilot (link).mkv", inode=e01.inode)

    matching.run_media_to_torrent_matching(db_session, tracker, Tracker())

    (candidate,) = db_session.query(Candidate).all()
    assert candidate.confidence == matching.CONFIDENCE_PIECE_VERIFIED


def test_too_many_files_of_that_size_are_not_read(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    monkeypatch.setattr(torrent_layout, "MAX_CONTENT_CANDIDATES", 1)  # E01 ed E02 hanno la stessa size
    _disk, tracker, _files = _library(db_session, tmp_path, with_srt=False)
    adapter = Tracker()

    matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    (candidate,) = db_session.query(Candidate).all()
    assert candidate.ambiguity_reason == "season_pack_partial"
    assert adapter.downloads == []  # niente da verificare: nessun download


def test_a_pack_of_files_not_in_the_library_costs_no_download(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _files = _library(db_session, tmp_path, with_srt=False)
    files = {"Show - S02 - 01 - Altro.mkv": b"x" * 70, "Show - S02 - 02 - Altro.mkv": b"y" * 80}
    adapter = Tracker(files)

    matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    assert adapter.downloads == []
    assert all(c.confidence == matching.CONFIDENCE_NO_MATCH for c in db_session.query(Candidate).all())


def test_each_file_is_read_once_per_run(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _files = _library(db_session, tmp_path, with_srt=False)
    reads = []
    real = torrent_layout.verify_file_pieces

    def counting(path, *args, **kwargs):
        reads.append((path, args[3]))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(torrent_layout, "verify_file_pieces", counting)

    # Il pack si valuta dal catalogo e poi dal .torrent vero: i piece si leggono una volta.
    matching.run_media_to_torrent_matching(db_session, tracker, Tracker())

    assert reads and len(reads) == len(set(reads))
