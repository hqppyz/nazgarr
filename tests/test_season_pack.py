"""Season pack e torrent con file extra: abbinamento (nazgarr/torrents/layout.py),
matching (una valutazione e un download per pack, nessuna review doppia),
esecuzione nei due versi e tolleranza del recheck per gli extra mancanti.
Filesystem vero in tmp_path, nessuna chiamata di rete."""

import hashlib
import os
from datetime import UTC, datetime

import pytest

from nazgarr.adapters.torrent_client.base import ClientTorrentInfo, TorrentAddTimeoutError, TorrentStatus
from nazgarr.adapters.tracker.base import TorrentCandidate
from nazgarr.core.models import (
    Candidate,
    ClientTorrent,
    ClientTorrentFile,
    Disk,
    MatchReview,
    MediaFile,
    MediaItem,
    SeedFile,
    SeedJob,
    TorrentClient,
    Tracker,
)
from nazgarr.integrations.arr import ArrIndex
from nazgarr.reseed import executor, matching, pipeline

PIECE = 16
FOLDER = "Show.S01.1080p-GRP"
E01 = b"episode-one-data" * 4  # 64 byte, allineati ai piece
E02 = b"episode-two-data" * 4
SRT = b"1\n00:00 --> x\nHi\n\n"  # 20 byte
NFO = b"release notes, 30 bytes long.."


def _bencode(value) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, str):
        return _bencode(value.encode())
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0].encode() if isinstance(kv[0], str) else kv[0])
        return b"d" + b"".join(_bencode(k) + _bencode(v) for k, v in items) + b"e"
    raise TypeError(type(value))


PACK_FILES = {
    "Show.S01E01.1080p-GRP.mkv": E01,
    "Show.S01E02.1080p-GRP.mkv": E02,
    "Show.S01E01.1080p-GRP.en.srt": SRT,
    "Show.S01.1080p-GRP.nfo": NFO,
}


def _pack_torrent() -> bytes:
    stream = b"".join(PACK_FILES.values())
    pieces = b"".join(hashlib.sha1(stream[i : i + PIECE]).digest() for i in range(0, len(stream), PIECE))
    return _bencode({"info": {
        "name": FOLDER, "piece length": PIECE, "pieces": pieces,
        "files": [{"length": len(c), "path": [n]} for n, c in PACK_FILES.items()],
    }})


def _pack_candidate() -> TorrentCandidate:
    return TorrentCandidate(
        torrent_id_remote="900", info_hash=None, name="Show S01 1080p", size_bytes=sum(map(len, PACK_FILES.values())),
        file_list=list(PACK_FILES), mediainfo_unique_id=None, folder=FOLDER,
        download_link="https://t.example/torrent/download/900.pk",
        file_sizes={n: len(c) for n, c in PACK_FILES.items()},
    )


class PackTracker:
    def __init__(self, candidates):
        self.candidates = candidates
        self.searches = 0
        self.downloads = []

    def search_by_tmdb(self, tmdb_id):
        self.searches += 1
        return self.candidates

    def download_torrent(self, url):
        self.downloads.append(url)
        return _pack_torrent()


class FakeClient:
    def __init__(self, status=None):
        self.added = []
        self.status = status

    def add_torrent(self, url, save_path, force_recheck=True, expected_info_hash=None):
        assert force_recheck is True
        self.added.append((url, save_path))
        return "packhash"

    def get_torrent_status(self, info_hash):
        return self.status


def _library(db_session, tmp_path, names=("Show - S01E01 - Pilot.mkv", "Show - S01E02 - Second.mkv"),
             with_srt=True):
    """Stagione in libreria come la organizza Sonarr: nomi rinominati,
    sottotitolo rinominato accanto all'episodio 1."""
    season = tmp_path / "media" / "tv" / "Show" / "Season 01"
    season.mkdir(parents=True)
    (tmp_path / "torrents").mkdir()
    disk = Disk(label="d", root_path=str(tmp_path), media_rel_path="media", torrents_rel_path="torrents")
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    db_session.add_all([disk, tracker])
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    files = []
    for ep, (name, content) in enumerate(zip(names, (E01, E02), strict=True), start=1):
        (season / name).write_bytes(content)
        item = MediaItem(content_type="tv", tmdb_id=1399, season_number=1, episode_number=ep)
        db_session.add(item)
        db_session.commit()
        mf = MediaFile(
            disk_id=disk.id, relative_path=f"media/tv/Show/Season 01/{name}", size_bytes=len(content),
            st_dev=1, inode=ep, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        )
        db_session.add(mf)
        files.append(mf)
    if with_srt:
        srt_name = "Show - S01E01 - Pilot.en.srt"
        (season / srt_name).write_bytes(SRT)
        db_session.add(MediaFile(
            disk_id=disk.id, relative_path=f"media/tv/Show/Season 01/{srt_name}", size_bytes=len(SRT),
            st_dev=1, inode=50, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        ))
    db_session.commit()
    return disk, tracker, files


def _no_mediainfo(monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)


def test_pack_matched_via_guessit_is_evaluated_and_downloaded_once(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, e02) = _library(db_session, tmp_path)
    adapter = PackTracker([_pack_candidate()])

    totals = matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    assert totals["files"] == 2
    assert len(adapter.downloads) == 1  # un solo .torrent per tutto il pack
    (candidate,) = db_session.query(Candidate).all()  # valutato una volta, non per episodio
    assert candidate.confidence == matching.CONFIDENCE_PIECE_VERIFIED
    by_path = {f.torrent_path: f for f in candidate.files}
    assert by_path["Show.S01E01.1080p-GRP.mkv"].media_file_id == e01.id
    assert by_path["Show.S01E02.1080p-GRP.mkv"].media_file_id == e02.id
    assert by_path["Show.S01E01.1080p-GRP.en.srt"].media_file_id is not None  # rinominato: estensione + size
    assert by_path["Show.S01.1080p-GRP.nfo"].media_file_id is None
    assert db_session.query(MatchReview).count() == 1


def test_pack_with_a_missing_episode_is_partial_and_never_queued(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, (_e01, e02) = _library(db_session, tmp_path)
    db_session.delete(e02)
    db_session.commit()

    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))

    (candidate,) = db_session.query(Candidate).all()
    assert candidate.ambiguity_reason == "season_pack_partial"
    assert candidate.confidence == matching.CONFIDENCE_NO_MATCH
    assert db_session.query(MatchReview).count() == 0


def test_sonarr_history_maps_episodes_whose_names_guessit_cannot_parse(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, e02) = _library(db_session, tmp_path, names=("Pilot.mkv", "Second.mkv"), with_srt=False)
    index = ArrIndex()
    for name, imported in (("Show.S01E01.1080p-GRP.mkv", "Pilot.mkv"), ("Show.S01E02.1080p-GRP.mkv", "Second.mkv")):
        index.add_import(f"/data/torrents/tv/{FOLDER}/{name}", f"/data/media/tv/Show/Season 01/{imported}",
                         len(PACK_FILES[name]))

    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]), index)

    (candidate,) = db_session.query(Candidate).all()
    assert candidate.confidence == matching.CONFIDENCE_PIECE_VERIFIED
    assert {f.media_file_id for f in candidate.files if f.is_video} == {e01.id, e02.id}


def test_executing_a_pack_hardlinks_every_local_file_and_tolerates_missing_extras(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))
    review = db_session.query(MatchReview).one()
    client = FakeClient()

    seed_job = executor.execute_review(db_session, review, client)

    target = tmp_path / "torrents" / FOLDER
    assert (target / "Show.S01E01.1080p-GRP.mkv").read_bytes() == E01
    assert (target / "Show.S01E02.1080p-GRP.mkv").read_bytes() == E02
    assert (target / "Show.S01E01.1080p-GRP.en.srt").read_bytes() == SRT
    assert os.stat(target / "Show.S01E02.1080p-GRP.mkv").st_ino == os.stat(
        tmp_path / "media/tv/Show/Season 01/Show - S01E02 - Second.mkv").st_ino
    assert not (target / "Show.S01.1080p-GRP.nfo").exists()
    assert client.added == [("https://t.example/torrent/download/900.pk", str(tmp_path / "torrents"))]
    assert seed_job.expected_missing_bytes == len(NFO) + 2 * PIECE

    # Recheck: mancano solo i byte dell'nfo (più i piece condivisi) -> ok.
    client.status = TorrentStatus("packhash", "stalledDL", "failed", 0.9, incomplete=True, amount_left=40)
    executor.reconcile_seed_job(db_session, seed_job, client)
    assert (seed_job.recheck_status, seed_job.final_status) == ("ok", "seeding")


def test_a_pack_for_a_client_without_root_folders_is_hardlinked_without_it(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))

    class NoSubfolderClient(FakeClient):
        def content_layout(self):
            return "NoSubfolder"

        def add_torrent(self, url, save_path, force_recheck=True, expected_info_hash=None, content_layout="Original"):
            self.added.append((url, save_path, content_layout))
            return "packhash"

    client = NoSubfolderClient()
    executor.execute_review(db_session, db_session.query(MatchReview).one(), client)

    assert (tmp_path / "torrents" / "Show.S01E01.1080p-GRP.mkv").read_bytes() == E01
    assert not (tmp_path / "torrents" / FOLDER).exists()
    assert client.added == [("https://t.example/torrent/download/900.pk", str(tmp_path / "torrents"), "NoSubfolder")]


def test_recheck_missing_more_than_the_extras_still_fails(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))
    client = FakeClient()
    seed_job = executor.execute_review(db_session, db_session.query(MatchReview).one(), client)

    client.status = TorrentStatus("packhash", "stalledDL", "failed", 0.5, incomplete=True, amount_left=64)
    executor.reconcile_seed_job(db_session, seed_job, client)

    assert seed_job.final_status == "failed"


def test_failed_client_add_removes_only_the_new_hardlinks(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))

    db_session.query(Candidate).one().info_hash = "packhash"
    db_session.commit()

    class Down(FakeClient):
        def add_torrent(self, url, save_path, force_recheck=True, expected_info_hash=None):
            raise RuntimeError("client down")

        def get_torrent_info(self, info_hash):
            return None  # il client risponde: quel torrent non ce l'ha

    try:
        executor.execute_review(db_session, db_session.query(MatchReview).one(), Down())
    except executor.ExecutionError:
        pass
    assert not any((tmp_path / "torrents" / FOLDER).glob("*"))
    assert (tmp_path / "media/tv/Show/Season 01/Show - S01E01 - Pilot.mkv").exists()


class LateClient(FakeClient):
    """Accetta il torrent ma l'attesa del suo hash scade (il .torrent arriva
    dal tracker dopo il timeout): il caso del bug del reseed partito in download."""

    def __init__(self, has_torrent):
        super().__init__()
        self.has_torrent = has_torrent
        self.rechecks = []

    def add_torrent(self, url, save_path, force_recheck=True, expected_info_hash=None):
        self.added.append((url, save_path))
        raise TorrentAddTimeoutError("no new torrent within 30s")

    def get_torrent_info(self, info_hash):
        if not self.has_torrent:
            return None
        return ClientTorrentInfo(info_hash=info_hash, name=FOLDER, save_path=self.added[0][1], state="checkingUP")

    def recheck(self, info_hash):
        self.rechecks.append(info_hash)


def test_torrent_that_reached_the_client_after_an_add_error_keeps_its_hardlinks(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))
    db_session.query(Candidate).one().info_hash = "packhash"
    db_session.commit()
    client = LateClient(has_torrent=True)

    seed_job = executor.execute_review(db_session, db_session.query(MatchReview).one(), client)

    assert (tmp_path / "torrents" / FOLDER / "Show.S01E01.1080p-GRP.mkv").read_bytes() == E01
    assert (seed_job.final_status, seed_job.info_hash) == ("in_progress", "packhash")
    assert seed_job.recheck_status == "pending"
    assert client.rechecks == ["packhash"]


def test_add_timeout_without_the_torrent_in_the_client_still_keeps_the_hardlinks(db_session, tmp_path, monkeypatch):
    # Il client può ancora scaricare il .torrent dal tracker: senza i file
    # partirebbe in download. Un hardlink in più non costa spazio.
    _no_mediainfo(monkeypatch)
    _disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))
    db_session.query(Candidate).one().info_hash = "packhash"
    db_session.commit()

    with pytest.raises(executor.ExecutionError):
        executor.execute_review(db_session, db_session.query(MatchReview).one(), LateClient(has_torrent=False))

    assert (tmp_path / "torrents" / FOLDER / "Show.S01E01.1080p-GRP.mkv").read_bytes() == E01
    assert db_session.query(SeedJob).one().final_status == "failed"


def test_retry_of_a_failed_job_follows_the_torrent_already_in_the_client(db_session, tmp_path, monkeypatch):
    _no_mediainfo(monkeypatch)
    _disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))
    candidate = db_session.query(Candidate).one()
    candidate.info_hash = "packhash"
    db_session.commit()
    with pytest.raises(executor.ExecutionError):
        executor.execute_review(db_session, db_session.query(MatchReview).one(), LateClient(has_torrent=False))
    seed_job = db_session.query(SeedJob).one()

    client = LateClient(has_torrent=True)
    client.added.append(("x", str(tmp_path / "torrents")))
    client.status = TorrentStatus("packhash", "checkingUP", "pending", 0.4)
    executor.retry_seed_job(db_session, seed_job, client)

    assert (seed_job.info_hash, seed_job.final_status) == ("packhash", "in_progress")
    assert len(client.added) == 1  # nessuna nuova aggiunta


def test_pack_folder_still_on_disk_is_readded_to_the_client(db_session, tmp_path, monkeypatch):
    """torrent -> client: la cartella del pack è ancora sotto torrents/ ma
    nessun client la traccia più."""
    _no_mediainfo(monkeypatch)
    disk, tracker, (e01, e02) = _library(db_session, tmp_path, with_srt=False)
    pack_dir = tmp_path / "torrents" / "tv" / FOLDER
    pack_dir.mkdir(parents=True)
    run = pipeline.start_run(db_session, "manual")
    seeds = {}
    for name, content in PACK_FILES.items():
        (pack_dir / name).write_bytes(content)
        linked = {"Show.S01E01.1080p-GRP.mkv": e01.id, "Show.S01E02.1080p-GRP.mkv": e02.id}.get(name)
        sf = SeedFile(
            disk_id=disk.id, relative_path=f"torrents/tv/{FOLDER}/{name}", size_bytes=len(content), st_dev=1,
            inode=hash(name) % 10_000, media_file_id=linked, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        )
        db_session.add(sf)
        seeds[name] = sf
    db_session.commit()
    adapter = PackTracker([_pack_candidate()])

    totals = matching.run_torrent_to_client_matching(db_session, tracker, adapter)

    assert totals["files"] == 2 and len(adapter.downloads) == 1
    candidate = db_session.query(Candidate).filter_by(direction="torrent_to_client").one()
    assert candidate.confidence == matching.CONFIDENCE_PIECE_VERIFIED
    assert all(f.seed_file_id is not None for f in candidate.files)  # anche srt e nfo, nomi originali

    client = FakeClient()
    seed_job = executor.execute_review(db_session, db_session.query(MatchReview).one(), client)
    assert client.added == [("https://t.example/torrent/download/900.pk", str(tmp_path / "torrents" / "tv"))]
    assert seed_job.expected_missing_bytes == 0


def test_tracked_pack_folder_is_not_an_orphan(db_session, tmp_path):
    """Controllo di sanità sul lato torrent: un file tracciato da un client
    non è mai orfano, quindi non innesca il matching."""
    disk, _tracker, (e01, _e02) = _library(db_session, tmp_path, with_srt=False)
    run = pipeline.start_run(db_session, "manual")
    sf = SeedFile(disk_id=disk.id, relative_path=f"torrents/{FOLDER}/a.mkv", size_bytes=64, st_dev=1, inode=9,
                  media_file_id=e01.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC))
    client = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q", username="u", password="p")
    db_session.add_all([sf, client])
    db_session.commit()
    ct = ClientTorrent(torrent_client_id=client.id, info_hash="h", name=FOLDER, save_path="/x", state="uploading",
                       last_polled_at=datetime.now(UTC))
    db_session.add(ct)
    db_session.commit()
    db_session.add(ClientTorrentFile(client_torrent_id=ct.id, path_in_torrent=f"{FOLDER}/a.mkv", size_bytes=64,
                                     seed_file_id=sf.id, last_scan_id=run.id))
    db_session.commit()

    assert matching.orphan_seed_files_with_identity(db_session) == []


def test_review_api_summarizes_the_pack(db_session, tmp_path, monkeypatch):
    from nazgarr.api.reviews import ReviewResponse

    _no_mediainfo(monkeypatch)
    _disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))

    layout = ReviewResponse.from_model(db_session.query(MatchReview).one()).layout

    assert (layout.folder, layout.video_count, layout.videos_matched, layout.videos_piece_verified) == (FOLDER, 2, 2, 2)
    assert (layout.extra_count, layout.extras_missing, layout.extras_missing_bytes) == (2, 1, len(NFO))
    missing = [f.torrent_path for f in layout.files if f.local_path is None]
    assert missing == ["Show.S01.1080p-GRP.nfo"]


def test_health_ignores_excluded_files(db_session, tmp_path):
    from nazgarr.library import health

    disk, _tracker, (e01, _e02) = _library(db_session, tmp_path, with_srt=False)
    db_session.add(MediaFile(  # poster scritto dal media server: escluso dal preset di default
        disk_id=disk.id, relative_path="media/tv/Show/poster.jpg", size_bytes=10_000_000,
        st_dev=1, inode=77, last_scan_id=e01.last_scan_id, last_seen_at=datetime.now(UTC),
    ))
    db_session.commit()

    snapshot = health.compute_snapshot(db_session)

    assert snapshot["total_media_size"] == len(E01) + len(E02)


def test_nothing_is_executed_without_approval_by_default(db_session, tmp_path, monkeypatch):
    """Decisione dell'utente: niente che tocchi file o client parte senza
    una sua approvazione — nemmeno un pack verificato al 99%."""
    from nazgarr.core.models import SeedJob
    from nazgarr.reseed import review

    _no_mediainfo(monkeypatch)
    _disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))
    assert db_session.query(MatchReview).one().status == "auto_approved"  # consigliata, non eseguita

    counts = review.execute_auto_approved(db_session)

    assert counts == {"executed": 0, "waiting": 1}
    assert db_session.query(SeedJob).count() == 0
    assert not (tmp_path / "torrents" / FOLDER).exists()


def test_automatic_execution_only_when_the_user_turns_it_on(db_session, tmp_path, monkeypatch):
    from nazgarr.core import settings_repo
    from nazgarr.core.models import SeedJob
    from nazgarr.reseed import review

    _no_mediainfo(monkeypatch)
    _disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))
    settings_repo.set_setting(db_session, review.AUTO_EXECUTE_SETTING, "true")
    settings_repo.set_setting(db_session, review.VERIFY_SETTING, "false")  # verifica: tests/test_full_check.py
    monkeypatch.setattr(review, "_build_torrent_client_adapter_or_none", lambda session: (FakeClient(), None))

    counts = review.execute_auto_approved(db_session)

    assert counts == {"executed": 1, "waiting": 0}
    assert db_session.query(SeedJob).count() == 1


def test_pack_without_folder_in_the_catalog_is_recreated_inside_the_torrent_folder(db_session, tmp_path, monkeypatch):
    """Il caso reale: il catalogo UNIT3D non riportava la cartella del pack e
    gli hardlink finivano sciolti nella cartella dei torrent (recheck fallito).
    La struttura ora viene dal .torrent, con i nomi del torrent."""
    _no_mediainfo(monkeypatch)
    _library(db_session, tmp_path)
    tracker = db_session.query(Tracker).one()
    candidate = _pack_candidate()
    candidate.folder = None  # come lo restituisce il catalogo
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([candidate]))

    (c,) = db_session.query(Candidate).all()
    assert c.folder == FOLDER
    executor.execute_review(db_session, db_session.query(MatchReview).one(), FakeClient())

    target = tmp_path / "torrents" / FOLDER
    assert (target / "Show.S01E01.1080p-GRP.mkv").read_bytes() == E01  # nome del torrent, non della libreria
    assert not (tmp_path / "torrents" / "Show.S01E01.1080p-GRP.mkv").exists()


def test_executor_refuses_a_multi_file_candidate_with_unknown_folder(db_session, tmp_path, monkeypatch):
    import pytest

    _no_mediainfo(monkeypatch)
    _disk, tracker, _ = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))
    db_session.query(Candidate).one().folder = None  # candidato salvato da una versione precedente
    db_session.commit()

    with pytest.raises(executor.ExecutionError, match="folder is unknown"):
        executor.execute_review(db_session, db_session.query(MatchReview).one(), FakeClient())
    assert not any((tmp_path / "torrents").iterdir())


def test_after_a_successful_recheck_episodes_are_seeding_without_waiting_for_a_run(db_session, tmp_path, monkeypatch):
    """Il caso reale: pack in seed nel client ma episodi ancora "orphaned" e
    seed job "pending" fino alla run successiva."""
    from nazgarr.adapters.torrent_client.base import ClientTorrentFileInfo, ClientTorrentInfo
    from nazgarr.library import states as library
    from nazgarr.reseed import review

    _no_mediainfo(monkeypatch)
    _disk, tracker, (e01, e02) = _library(db_session, tmp_path)
    matching.run_media_to_torrent_matching(db_session, tracker, PackTracker([_pack_candidate()]))
    run = db_session.query(pipeline.RunLog).order_by(pipeline.RunLog.id.desc()).first()
    run.finished_at = datetime.now(UTC)
    client_row = TorrentClient(label="qbit private", adapter_type="qui", base_url="http://qui")
    db_session.add(client_row)
    db_session.commit()

    class SeedingClient(FakeClient):
        def get_torrent_info(self, info_hash):
            return ClientTorrentInfo(
                info_hash="packhash", name=FOLDER, save_path=str(tmp_path / "torrents"), state="uploading",
                files=[ClientTorrentFileInfo(path_in_torrent=f"{FOLDER}/{n}", size_bytes=len(c))
                       for n, c in PACK_FILES.items()],
            )

    client = SeedingClient(status=TorrentStatus("packhash", "uploading", "ok", 1.0))
    monkeypatch.setattr(review, "build_torrent_client_adapter", lambda row: client)
    seed_job = executor.execute_review(db_session, db_session.query(MatchReview).one(), client, client_row.id)
    assert {s["state"] for s in library.media_file_states(db_session) if s["relative_path"].endswith(".mkv")} == {
        "orphan_media"
    }

    assert review.reconcile_pending_seed_jobs(db_session) == {"reconciled": 1, "errors": 0}

    assert seed_job.final_status == "seeding"
    states = {s["id"]: s["state"] for s in library.media_file_states(db_session)}
    assert states[e01.id] == "seeding" and states[e02.id] == "seeding"


def test_reconcile_between_runs_is_scheduled_and_skipped_during_a_run(db_session, monkeypatch):
    from nazgarr import scheduler
    from nazgarr.reseed import review

    calls = []
    monkeypatch.setattr(review, "has_pending_seed_jobs", lambda session: True)
    monkeypatch.setattr(review, "reconcile_pending_seed_jobs", lambda session: calls.append(1))
    factory = lambda: db_session  # noqa: E731
    db_session.close = lambda: None  # la sessione del test resta aperta

    run = pipeline.start_run(db_session, "manual")  # run in corso: niente reconcile
    scheduler._reconcile_between_runs(factory)
    run.finished_at = datetime.now(UTC)
    db_session.commit()
    scheduler._reconcile_between_runs(factory)

    assert calls == [1]
    sched = scheduler.build_scheduler(lambda: db_session, "/tmp")
    assert sched.get_job(scheduler.RECONCILE_JOB_ID) is not None
