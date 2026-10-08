"""Pack ed episodi singoli dello stesso tracker (decisioni dell'utente,
2026-10-08): con l'opzione spenta vince il pack, accesa si propongono
entrambi e un episodio in seed in un formato si cerca nell'altro. Stessa
stagione di tests/test_season_pack.py, con i torrent dei singoli accanto."""

import hashlib
from datetime import UTC, datetime

from nazgarr.adapters.tracker.base import TorrentCandidate
from nazgarr.api.reviews import ReviewResponse
from nazgarr.core import settings_repo
from nazgarr.core.models import ClientTorrent, ClientTorrentFile, MatchReview, SeedFile, TorrentClient
from nazgarr.library.seeding import PACK_AND_SINGLES_SETTING
from nazgarr.reseed import matching, review
from tests.test_season_pack import (
    E01,
    E02,
    FOLDER,
    PIECE,
    _bencode,
    _library,
    _no_mediainfo,
    _pack_candidate,
    _pack_torrent,
)

SINGLES = {"901": ("Show.S01E01.1080p-GRP.mkv", E01), "902": ("Show.S01E02.1080p-GRP.mkv", E02)}


def _single_torrent(name: str, content: bytes) -> bytes:
    pieces = b"".join(hashlib.sha1(content[i : i + PIECE]).digest() for i in range(0, len(content), PIECE))
    return _bencode({"info": {"name": name, "piece length": PIECE, "pieces": pieces, "length": len(content)}})


def _single_candidate(torrent_id: str) -> TorrentCandidate:
    name, content = SINGLES[torrent_id]
    return TorrentCandidate(
        torrent_id_remote=torrent_id, info_hash=None, name=name, size_bytes=len(content), file_list=[name],
        mediainfo_unique_id=None, download_link=f"https://t.example/torrent/download/{torrent_id}.pk",
        file_sizes={name: len(content)},
    )


class Catalog:
    """Il tracker: il pack (900) e i due episodi singoli (901, 902)."""

    def __init__(self, ids=("900", "901", "902")):
        self.candidates = [_pack_candidate() if i == "900" else _single_candidate(i) for i in ids]
        self.downloads = []

    def search_by_tmdb(self, tmdb_id):
        return self.candidates

    def download_torrent(self, url):
        torrent_id = url.rsplit("/", 1)[1].split(".")[0]
        self.downloads.append(torrent_id)
        return _pack_torrent() if torrent_id == "900" else _single_torrent(*SINGLES[torrent_id])


def _active(db_session) -> dict[tuple[int, str], str]:
    """(media_file, torrent) -> stato delle review in coda."""
    return {
        (r.media_file_id, r.candidate.torrent_id_remote): r.status
        for r in db_session.query(MatchReview).filter(MatchReview.status.in_(review.READY_FOR_DECISION_STATUSES))
    }


def _seeding(db_session, disk, files, name, info_hash):
    """Un torrent di questo tracker nel client con questi media_file in seed
    (un seed_file collegato per ognuno)."""
    client = db_session.query(TorrentClient).first() or TorrentClient(
        label="q", adapter_type="qbittorrent", base_url="http://q", username="u", password="p")
    db_session.add(client)
    db_session.commit()
    torrent = ClientTorrent(torrent_client_id=client.id, info_hash=info_hash, name=name, save_path="/x",
                            state="uploading", tracker_url="https://t.example", last_polled_at=datetime.now(UTC))
    db_session.add(torrent)
    db_session.commit()
    for mf in files:
        path = f"{name}/{mf.relative_path.rsplit('/', 1)[1]}" if len(files) > 1 else mf.relative_path.rsplit("/", 1)[1]
        sf = SeedFile(disk_id=disk.id, relative_path=f"torrents/{path}", size_bytes=mf.size_bytes, st_dev=2,
                      inode=hash((name, mf.id)) % 100_000, media_file_id=mf.id, last_scan_id=mf.last_scan_id,
                      last_seen_at=datetime.now(UTC))
        db_session.add(sf)
        db_session.commit()
        db_session.add(ClientTorrentFile(client_torrent_id=torrent.id, path_in_torrent=path,
                                         size_bytes=mf.size_bytes, seed_file_id=sf.id, last_scan_id=mf.last_scan_id))
    db_session.commit()


def _turn_on(db_session):
    settings_repo.set_setting(db_session, PACK_AND_SINGLES_SETTING, "true")


def test_without_the_option_the_pack_wins_and_no_single_is_proposed(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, _e02) = _library(db_session, tmp_path)

    matching.run_media_to_torrent_matching(db_session, tracker, Catalog(ids=("901", "902", "900")))

    # Il singolo dell'episodio 1 era primo nel catalogo e ugualmente verificato.
    assert _active(db_session) == {(e01.id, "900"): "auto_approved"}


def test_a_pack_found_later_replaces_the_singles_in_the_queue(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, e02) = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, Catalog(ids=("901", "902")))
    assert set(_active(db_session)) == {(e01.id, "901"), (e02.id, "902")}

    matching.run_media_to_torrent_matching(db_session, tracker, Catalog(), force=True)

    assert set(_active(db_session)) == {(e01.id, "900")}


def test_a_rejected_pack_does_not_come_back_from_the_other_episode(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, e02) = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, Catalog())
    review.reject(db_session, db_session.query(MatchReview).one())

    matching.run_media_to_torrent_matching(db_session, tracker, Catalog(), force=True)

    assert set(_active(db_session)) == {(e01.id, "901"), (e02.id, "902")}


def test_with_the_option_both_formats_are_proposed(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, e02) = _library(db_session, tmp_path)
    _turn_on(db_session)

    matching.run_media_to_torrent_matching(db_session, tracker, Catalog())

    assert set(_active(db_session)) == {(e01.id, "900"), (e01.id, "901"), (e02.id, "902")}


def test_episodes_seeding_in_the_pack_are_searched_as_singles(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    disk, tracker, (e01, e02) = _library(db_session, tmp_path)
    _seeding(db_session, disk, [e01, e02], FOLDER, "packhash")
    catalog = Catalog()

    matching.run_media_to_torrent_matching(db_session, tracker, catalog)
    assert _active(db_session) == {}  # senza l'opzione: in seed, non si cercano

    _turn_on(db_session)
    matching.run_media_to_torrent_matching(db_session, tracker, catalog, force=True)

    assert set(_active(db_session)) == {(e01.id, "901"), (e02.id, "902")}
    assert "900" not in catalog.downloads  # il pack non serviva: mai valutato
    response = ReviewResponse.from_model(db_session.query(MatchReview).filter_by(media_file_id=e01.id).one())
    assert (response.format, response.seeding_here, response.season_number, response.episode_number) == (
        "single", ["pack"], 1, 1)
    assert response.tracker == tracker.label


def test_episodes_seeding_as_singles_get_the_pack_until_it_seeds(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    disk, tracker, (e01, e02) = _library(db_session, tmp_path)
    _seeding(db_session, disk, [e01], "Show.S01E01.1080p-GRP.mkv", "h1")
    _seeding(db_session, disk, [e02], "Show.S01E02.1080p-GRP.mkv", "h2")
    _turn_on(db_session)

    matching.run_media_to_torrent_matching(db_session, tracker, Catalog())

    assert set(_active(db_session)) == {(e01.id, "900")}
    assert review.close_resolved_reviews(db_session) == 0  # in seed come singolo: il pack serve ancora

    _seeding(db_session, disk, [e01, e02], FOLDER, "packhash")
    assert review.close_resolved_reviews(db_session) == 1
