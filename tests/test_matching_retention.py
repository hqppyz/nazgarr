"""Quello che il matching salva a ogni ricerca (audit 2026-10-18): i torrent
che non riguardano il file cercato non diventano righe di audit, e una nuova
ricerca aggiorna le righe di prima invece di aggiungerne altre. Filesystem
vero in tmp_path, nessuna chiamata di rete."""

import hashlib
from datetime import UTC, datetime

from nazgarr.adapters.tracker.base import TorrentCandidate
from nazgarr.core.models import Candidate, MatchReview, SeedFile
from nazgarr.reseed import matching, pipeline
from tests.test_season_pack import (
    E01,
    E02,
    FOLDER,
    PACK_FILES,
    PIECE,
    PackTracker,
    _bencode,
    _library,
    _no_mediainfo,
    _pack_candidate,
    _pack_torrent,
)


def _single(remote: str, name: str, size: int) -> TorrentCandidate:
    return TorrentCandidate(
        torrent_id_remote=remote, info_hash=None, name=name, size_bytes=size, file_list=[name],
        mediainfo_unique_id=None, folder=None, download_link=None, file_sizes={name: size},
    )


def test_singles_of_other_episodes_are_not_stored(db_session, tmp_path, monkeypatch):
    # La ricerca è per tmdb_id della serie: ogni singolo di un altro episodio
    # finiva abbinato all'episodio cercato, a confidence 0, per ogni episodio.
    _no_mediainfo(monkeypatch)
    _disk, tracker, _files = _library(db_session, tmp_path)
    others = [_single(str(100 + n), f"Show.S01E{n:02d}.1080p-GRP.mkv", 1000 + n) for n in range(3, 9)]
    other_release = _single("200", "Show.S01E01.720p-OTHER.mkv", 999)

    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([*others, other_release]))

    # Solo l'altra release dello stesso episodio resta, per E01: per E02 è un altro episodio.
    rows = db_session.query(Candidate).all()
    assert [(c.torrent_id_remote, c.ambiguity_reason) for c in rows] == [("200", "size_mismatch")]


def test_a_double_episode_file_with_the_episode_is_still_evaluated(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, e02) = _library(db_session, tmp_path)

    matching.run_media_to_torrent_matching(
        db_session, tracker, PackTracker([_single("300", "Show.S01E01E02.1080p-GRP.mkv", 5000)]))

    assert {c.media_item_id for c in db_session.query(Candidate)} == {e01.media_item_id, e02.media_item_id}


def test_a_single_with_the_same_size_is_left_to_the_pieces(db_session, tmp_path, monkeypatch):
    # A size uguale non si scarta mai sul nome: lo decidono i piece hash.
    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, _e02) = _library(db_session, tmp_path)

    matching.run_media_to_torrent_matching(
        db_session, tracker, PackTracker([_single("400", "Show.S01E05.1080p-GRP.mkv", len(E01))]))

    assert db_session.query(Candidate).filter_by(media_item_id=e01.media_item_id).count() == 1


def test_a_torrent_with_unsafe_names_in_the_catalog_is_ignored(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _files = _library(db_session, tmp_path)
    hostile = TorrentCandidate(
        torrent_id_remote="666", info_hash=None, name="x", size_bytes=len(E01),
        file_list=["../../Show.S01E01.1080p-GRP.mkv"], mediainfo_unique_id=None, folder=None, download_link=None,
        file_sizes={"../../Show.S01E01.1080p-GRP.mkv": len(E01)},
    )

    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([hostile]))

    assert db_session.query(Candidate).count() == 0


OTHER_FOLDER = "Show.S01.1080p-OTHER"
OTHER_FILES = {name.replace("GRP", "OTHER"): content for name, content in PACK_FILES.items()}


def _other_pack_torrent() -> bytes:
    stream = b"".join(OTHER_FILES.values())
    pieces = b"".join(hashlib.sha1(stream[i : i + PIECE]).digest() for i in range(0, len(stream), PIECE))
    return _bencode({"info": {
        "name": OTHER_FOLDER, "piece length": PIECE, "pieces": pieces,
        "files": [{"length": len(c), "path": [n]} for n, c in OTHER_FILES.items()],
    }})


def test_a_pack_without_the_seed_file_does_not_hide_it_from_its_own_files(db_session, tmp_path, monkeypatch):
    # torrent -> client: due cartelle di pack su disco, nessuna seguita da un
    # client. Il pack B valutato dal primo file di A finiva in evaluated_packs
    # ("parziale"): i file di B lo saltavano e non tornavano mai in seed.
    _no_mediainfo(monkeypatch)
    disk, tracker, (e01, e02) = _library(db_session, tmp_path, with_srt=False)
    run = pipeline.start_run(db_session, "manual")
    inode = 100
    for folder, files in ((FOLDER, PACK_FILES), (OTHER_FOLDER, OTHER_FILES)):
        pack_dir = tmp_path / "torrents" / "tv" / folder
        pack_dir.mkdir(parents=True)
        for name, content in files.items():
            (pack_dir / name).write_bytes(content)
            linked = e01.id if content is E01 else e02.id if content is E02 else None
            inode += 1
            db_session.add(SeedFile(
                disk_id=disk.id, relative_path=f"torrents/tv/{folder}/{name}", size_bytes=len(content), st_dev=1,
                inode=inode, media_file_id=linked, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
            ))
    db_session.commit()
    other = TorrentCandidate(
        torrent_id_remote="901", info_hash=None, name="Show S01 1080p OTHER",
        size_bytes=sum(map(len, OTHER_FILES.values())), file_list=list(OTHER_FILES), mediainfo_unique_id=None,
        folder=OTHER_FOLDER, download_link="https://t.example/torrent/download/901.pk",
        file_sizes={n: len(c) for n, c in OTHER_FILES.items()},
    )

    class TwoPacks(PackTracker):
        def download_torrent(self, url):
            self.downloads.append(url)
            return _other_pack_torrent() if "901" in url else _pack_torrent()

    matching.run_torrent_to_client_matching(db_session, tracker, TwoPacks([_pack_candidate(), other]))

    reviewed = {r.candidate.torrent_id_remote for r in db_session.query(MatchReview)}
    assert reviewed == {"900", "901"}
    # Nessuna riga per il pack valutato da un file che non ne fa parte.
    assert db_session.query(Candidate).count() == 2


def test_a_new_search_drops_what_no_longer_concerns_the_file(db_session, tmp_path, monkeypatch):
    # Righe salvate da una ricerca di prima (i singoli degli altri episodi,
    # un torrent tolto dal tracker): la ricerca dopo le toglie, ma non quelle
    # che una review usa.
    from nazgarr.core import settings_repo

    _no_mediainfo(monkeypatch)
    settings_repo.set_setting(db_session, "rematch_interval_days", "0")
    _disk, tracker, (e01, _e02) = _library(db_session, tmp_path)
    others = [_single(str(100 + n), f"Show.S01E{n:02d}.1080p-GRP.mkv", 1000 + n) for n in range(3, 6)]
    gone = _single("500", "Show.S01E01.WEB-GONE.mkv", 998)
    with monkeypatch.context() as old:
        old.setattr(matching, "_unrelated", lambda *a: False)  # come prima del fix
        matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([*others, gone]))
    assert db_session.query(Candidate).filter_by(media_item_id=e01.media_item_id).count() == 4

    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([]))

    assert db_session.query(Candidate).count() == 0
