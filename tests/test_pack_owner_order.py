"""Una proposta di pack per stagione, qualunque sia l'ordine in cui il
matching cerca gli episodi (regressione, 2026-10-22). Da 21fa287 gli orfani
si cercano per serie, stagione ed episodio, prima nell'ordine delle righe
(lo scanner le inserisce nell'ordine del filesystem): il pack proposto per
l'episodio con l'id più basso lo valutava prima un episodio precedente, che
non poteva proporlo (occupato da quella proposta) ma lo segnava come già
valutato. L'episodio della proposta lo saltava, il suo singolo prendeva il
posto del pack e gli episodi dopo di lui avevano ognuno il suo singolo.
Stagione di quattro episodi, filesystem vero in tmp_path, nessuna rete."""

import hashlib
from datetime import UTC, datetime

import pytest

from nazgarr.adapters.tracker.base import TorrentCandidate
from nazgarr.core import settings_repo
from nazgarr.core.models import Disk, MatchReview, MediaFile, MediaItem, SeedFile, Tracker
from nazgarr.integrations.arr import ArrGrab, ArrIndex
from nazgarr.library.seeding import PACK_AND_SINGLES_SETTING
from nazgarr.reseed import matching, pipeline, review
from tests.test_season_pack import _bencode, _no_mediainfo

PIECE = 16
FOLDER = "Show.S01.1080p-GRP"
PACK_ID = "900"
EPISODES = (1, 2, 3, 4)
# Una size diversa per episodio, multipla del piece: il singolo di un altro
# episodio si scarta già dal nome e dalla size, senza righe a confidence 0.
CONTENT = {ep: f"episode-{ep}-data".encode().ljust(PIECE, b"-") * (ep + 1) for ep in EPISODES}
NAMES = {ep: f"Show.S01E{ep:02d}.1080p-GRP.mkv" for ep in EPISODES}
SINGLE = {ep: str(900 + ep) for ep in EPISODES}
SHUFFLED = (3, 1, 4, 2)  # l'ordine delle righe: la proposta è del terzo episodio


def _pieces(data: bytes) -> bytes:
    return b"".join(hashlib.sha1(data[i : i + PIECE]).digest() for i in range(0, len(data), PIECE))


def _pack_torrent() -> bytes:
    return _bencode({"info": {
        "name": FOLDER, "piece length": PIECE, "pieces": _pieces(b"".join(CONTENT[ep] for ep in EPISODES)),
        "files": [{"length": len(CONTENT[ep]), "path": [NAMES[ep]]} for ep in EPISODES],
    }})


def _single_torrent(ep: int) -> bytes:
    return _bencode({"info": {"name": NAMES[ep], "piece length": PIECE, "pieces": _pieces(CONTENT[ep]),
                              "length": len(CONTENT[ep])}})


def _link(torrent_id: str) -> str:
    return f"https://t.example/torrent/download/{torrent_id}.pk"


class Catalog:
    """Il tracker: il pack della stagione e il singolo di ogni episodio,
    della stessa release (gli stessi byte)."""

    def __init__(self):
        pack_files = [NAMES[ep] for ep in EPISODES]
        self.candidates = [TorrentCandidate(
            torrent_id_remote=PACK_ID, info_hash=None, name="Show S01 1080p",
            size_bytes=sum(map(len, CONTENT.values())), file_list=pack_files, mediainfo_unique_id=None,
            folder=FOLDER, download_link=_link(PACK_ID), file_sizes={NAMES[ep]: len(CONTENT[ep]) for ep in EPISODES},
        )] + [TorrentCandidate(
            torrent_id_remote=SINGLE[ep], info_hash=None, name=NAMES[ep], size_bytes=len(CONTENT[ep]),
            file_list=[NAMES[ep]], mediainfo_unique_id=None, download_link=_link(SINGLE[ep]),
            file_sizes={NAMES[ep]: len(CONTENT[ep])},
        ) for ep in EPISODES]

    def search_by_tmdb(self, tmdb_id):
        return self.candidates

    def download_torrent(self, url):
        torrent_id = url.rsplit("/", 1)[1].split(".")[0]
        return _pack_torrent() if torrent_id == PACK_ID else _single_torrent(int(torrent_id) - 900)


def _season(db_session, tmp_path, rows=SHUFFLED):
    """La stagione in libreria, coi media_file inseriti nell'ordine degli
    episodi `rows`: il loro id, quindi l'ordine delle righe."""
    season = tmp_path / "media" / "tv" / "Show" / "Season 01"
    season.mkdir(parents=True)
    (tmp_path / "torrents").mkdir()
    disk = Disk(label="d", root_path=str(tmp_path), media_rel_path="media", torrents_rel_path="torrents")
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    db_session.add_all([disk, tracker])
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    files = {}
    for ep in rows:
        name = f"Show - S01E{ep:02d} - Title.mkv"
        (season / name).write_bytes(CONTENT[ep])
        item = MediaItem(content_type="tv", tmdb_id=1399, season_number=1, episode_number=ep)
        db_session.add(item)
        db_session.commit()
        files[ep] = MediaFile(
            disk_id=disk.id, relative_path=f"media/tv/Show/Season 01/{name}", size_bytes=len(CONTENT[ep]),
            st_dev=1, inode=ep, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        )
        db_session.add(files[ep])
        db_session.commit()
    return disk, tracker, files


_SERIES_ORDER = matching._series_order

# L'ordine in cui il matching cerca gli orfani: quello del codice (dal primo
# episodio), quello delle righe (prima di 21fa287) e quello rovesciato.
ORDERS = {
    "series": _SERIES_ORDER,
    "rows": lambda orphan, side: (orphan.id,),
    "reversed": lambda orphan, side: tuple(-value for value in _SERIES_ORDER(orphan, side)),
}


def _in_order(monkeypatch, order: str) -> None:
    monkeypatch.setattr(matching, "_series_order", ORDERS[order])


def _search(db_session, tracker, monkeypatch, order: str, **kwargs) -> None:
    _in_order(monkeypatch, order)
    matching.run_media_to_torrent_matching(db_session, tracker, Catalog(), **kwargs)


def _active(db_session) -> dict[tuple[int, str], str]:
    """(episodio, torrent) -> stato delle review in coda."""
    return {
        (r.media_file.media_item.episode_number, r.candidate.torrent_id_remote): r.status
        for r in db_session.query(MatchReview).filter(MatchReview.status.in_(review.READY_FOR_DECISION_STATUSES))
    }


@pytest.mark.parametrize("rows", [SHUFFLED, EPISODES], ids=["rows-shuffled", "rows-in-episode-order"])
@pytest.mark.parametrize("order", list(ORDERS))
def test_a_new_search_keeps_the_one_pack_proposal_in_any_order(db_session, tmp_path, monkeypatch, rows, order):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _files = _season(db_session, tmp_path, rows)
    # La proposta di prima: del primo episodio nell'ordine delle righe.
    _search(db_session, tracker, monkeypatch, "rows")
    owner = rows[0]
    (proposal,) = db_session.query(MatchReview).all()
    assert _active(db_session) == {(owner, PACK_ID): "auto_approved"}

    _search(db_session, tracker, monkeypatch, order, force=True)

    # La stessa review, confermata: nessun singolo, nessun rifiuto di sistema.
    assert _active(db_session) == {(owner, PACK_ID): "auto_approved"}
    assert [r.id for r in db_session.query(MatchReview)] == [proposal.id]


@pytest.mark.parametrize("order", list(ORDERS))
def test_with_the_singles_in_the_sonarr_history_the_pack_proposal_stays(db_session, tmp_path, monkeypatch, order):
    """La history dà a ogni episodio il suo singolo: il pack lo trova la
    ricerca dei pack che segue (find_candidates)."""
    _no_mediainfo(monkeypatch)
    _disk, tracker, files = _season(db_session, tmp_path)
    index = ArrIndex()
    for ep, mf in files.items():
        index.add_grab(f"{tmp_path}/{mf.relative_path}", mf.size_bytes, ArrGrab(
            tracker_host="t.example", torrent_id_remote=SINGLE[ep], download_url=_link(SINGLE[ep]), info_hash=None,
            indexer="t"))
    _search(db_session, tracker, monkeypatch, "rows", arr_index=index)
    (proposal,) = db_session.query(MatchReview).all()
    assert _active(db_session) == {(3, PACK_ID): "auto_approved"}

    _search(db_session, tracker, monkeypatch, order, arr_index=index, force=True)

    assert _active(db_session) == {(3, PACK_ID): "auto_approved"}
    assert [r.id for r in db_session.query(MatchReview)] == [proposal.id]


@pytest.mark.parametrize("order", list(ORDERS))
def test_with_pack_and_singles_the_pack_proposal_stays_next_to_the_singles(db_session, tmp_path, monkeypatch, order):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _files = _season(db_session, tmp_path)
    settings_repo.set_setting(db_session, PACK_AND_SINGLES_SETTING, "true")
    _search(db_session, tracker, monkeypatch, "rows")
    expected = {(3, PACK_ID): "auto_approved", **{(ep, SINGLE[ep]): "auto_approved" for ep in EPISODES}}
    assert _active(db_session) == expected

    _search(db_session, tracker, monkeypatch, order, force=True)

    assert _active(db_session) == expected
    assert db_session.query(MatchReview).count() == len(expected)  # nessuna rifatta


@pytest.mark.parametrize("order", list(ORDERS))
def test_a_pack_that_no_longer_matches_gives_way_to_the_singles_in_any_order(
        db_session, tmp_path, monkeypatch, order):
    """Il quarto episodio sostituito da un upgrade: il pack non si ricrea più.
    Ogni episodio che ha ancora il suo singolo lo riceve, anche quelli
    cercati prima dell'episodio che proponeva il pack: il pack che la loro
    ricerca dà per non plausibile non li copre più."""
    _no_mediainfo(monkeypatch)
    _disk, tracker, files = _season(db_session, tmp_path)
    _search(db_session, tracker, monkeypatch, "rows")
    assert _active(db_session) == {(3, PACK_ID): "auto_approved"}
    upgrade = b"a-better-episode" * 7
    (tmp_path / files[4].relative_path).write_bytes(upgrade)
    files[4].size_bytes = len(upgrade)
    db_session.commit()

    _search(db_session, tracker, monkeypatch, order, force=True)

    assert _active(db_session) == {(ep, SINGLE[ep]): "auto_approved" for ep in (1, 2, 3)}


@pytest.mark.parametrize("order", list(ORDERS))
def test_torrent_to_client_the_pack_proposal_of_a_seed_file_stays(db_session, tmp_path, monkeypatch, order):
    """Lato torrent: la cartella del pack è ancora sotto torrents/ e nessun
    client la segue, coi seed_file inseriti in ordine sparso."""
    _no_mediainfo(monkeypatch)
    disk, tracker, files = _season(db_session, tmp_path, EPISODES)
    settings_repo.set_setting(db_session, "rematch_interval_days", "0")  # questa direzione non ha force
    pack_dir = tmp_path / "torrents" / "tv" / FOLDER
    pack_dir.mkdir(parents=True)
    run = pipeline.start_run(db_session, "manual")
    seeds = {}
    for ep in SHUFFLED:
        (pack_dir / NAMES[ep]).write_bytes(CONTENT[ep])
        seeds[ep] = SeedFile(
            disk_id=disk.id, relative_path=f"torrents/tv/{FOLDER}/{NAMES[ep]}", size_bytes=len(CONTENT[ep]),
            st_dev=1, inode=100 + ep, media_file_id=files[ep].id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        )
        db_session.add(seeds[ep])
        db_session.commit()
    episode_of = {sf.id: ep for ep, sf in seeds.items()}

    def active():
        return {
            (episode_of[r.seed_file_id], r.candidate.torrent_id_remote)
            for r in db_session.query(MatchReview).filter(MatchReview.status.in_(review.READY_FOR_DECISION_STATUSES))
        }

    _in_order(monkeypatch, "rows")
    matching.run_torrent_to_client_matching(db_session, tracker, Catalog())
    proposal = db_session.query(MatchReview).filter_by(seed_file_id=seeds[3].id).one()
    expected = {(3, PACK_ID), (1, SINGLE[1]), (2, SINGLE[2]), (4, SINGLE[4])}
    assert active() == expected

    _in_order(monkeypatch, order)
    matching.run_torrent_to_client_matching(db_session, tracker, Catalog())

    assert active() == expected
    assert db_session.query(MatchReview).filter_by(seed_file_id=seeds[3].id).one().id == proposal.id
