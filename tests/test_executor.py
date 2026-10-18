import hashlib
import os
from datetime import UTC, datetime

import pytest

from nazgarr.adapters.torrent_client.base import TorrentStatus
from nazgarr.core.models import (
    Candidate,
    Disk,
    DiskTorrentClient,
    MatchReview,
    MediaFile,
    MediaItem,
    SeedFile,
    TorrentClient,
    Tracker,
)
from nazgarr.reseed import executor, pipeline
from nazgarr.torrents.metainfo import compute_info_hash
from tests.test_season_pack import _bencode


def _movie_torrent(content: bytes = b"content", name: str = "Movie.2024.mkv") -> bytes:
    return _bencode({"info": {"name": name, "piece length": 16, "length": len(content),
                              "pieces": hashlib.sha1(content).digest()}})


# La funzione vera, prima che il fixture qui sotto la sostituisca in ogni test.
_REAL_DOWNLOAD_TORRENT = executor._download_torrent


@pytest.fixture(autouse=True)
def _tracker_torrent(monkeypatch):
    """Il .torrent che l'esecutore scarica dal tracker (mai il link al
    client): quello del film dei test, salvo dove un test lo cambia."""
    served = {"content": _movie_torrent(), "links": []}

    def download(candidate):
        served["links"].append(candidate.download_link)
        return served["content"]

    monkeypatch.setattr(executor, "_download_torrent", download)
    return served


def _sent(path):
    with open(path, "rb") as fh:
        return fh.read()


class FakeAdapter:
    def __init__(self, info_hash="deadbeef", recheck_status="ok"):
        self.info_hash = info_hash
        self.recheck_status = recheck_status
        self.add_torrent_calls = []

    def add_torrent(self, torrent_file_or_url, save_path, force_recheck=True, expected_info_hash=None):
        assert force_recheck is True
        self.add_torrent_calls.append({"url": torrent_file_or_url, "save_path": save_path,
                                       "content": _sent(torrent_file_or_url), "expected": expected_info_hash})
        return self.info_hash

    def get_torrent_status(self, info_hash):
        return TorrentStatus(info_hash=info_hash, state="uploading", recheck_status=self.recheck_status, progress=1.0)

    def list_torrents(self):
        return []


def _make_disk_media_path(tmp_path):
    root = tmp_path / "disk1"
    (root / "media" / "movies").mkdir(parents=True)
    (root / "torrents").mkdir(parents=True)
    return root


def _base_setup(db_session, tmp_path):
    root = _make_disk_media_path(tmp_path)
    disk = Disk(label="d", root_path=str(root), media_rel_path="media/movies", torrents_rel_path="torrents")
    db_session.add(disk)
    db_session.commit()
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    db_session.add(tracker)
    db_session.commit()
    item = MediaItem(content_type="movie", tmdb_id=1)
    db_session.add(item)
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    return root, disk, tracker, item, run


def test_execute_media_to_torrent_creates_hardlink_and_adds_torrent(db_session, tmp_path):
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)

    media_file_path = root / "media" / "movies" / "Movie.2024.mkv"
    media_file_path.write_bytes(b"content")
    media_file = MediaFile(
        disk_id=disk.id, relative_path="media/movies/Movie.2024.mkv", size_bytes=7,
        st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(media_file)
    db_session.commit()

    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="Movie.2024.mkv",
        size_bytes=7, source="catalog_search", direction="media_to_torrent", confidence=1.0,
        download_link="https://t.example/dl/1", file_list_json='["Movie.2024.mkv"]',
    )
    db_session.add(candidate)
    db_session.commit()
    match_review = MatchReview(candidate_id=candidate.id, media_file_id=media_file.id, status="approved")
    db_session.add(match_review)
    db_session.commit()

    adapter = FakeAdapter()
    seed_job = executor.execute_review(db_session, match_review, adapter)

    expected_link = root / "torrents" / "Movie.2024.mkv"
    assert expected_link.is_file()
    assert os.path.samefile(media_file_path, expected_link)
    assert seed_job.hardlink_created_at is not None
    assert seed_job.info_hash == "deadbeef"
    assert seed_job.recheck_status == "pending"
    assert len(adapter.add_torrent_calls) == 1


class LayoutAdapter(FakeAdapter):
    """Un client con "Layout del contenuto" impostato dall'utente."""

    def __init__(self, layout):
        super().__init__()
        self.layout = layout

    def content_layout(self):
        return self.layout

    def add_torrent(self, torrent_file_or_url, save_path, force_recheck=True, expected_info_hash=None,
                    content_layout="Original"):
        self.add_torrent_calls.append({"url": torrent_file_or_url, "save_path": save_path, "layout": content_layout})
        return self.info_hash


def _movie_review(db_session, tmp_path, folder=None):
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    (root / "media" / "movies" / "Movie.2024.mkv").write_bytes(b"content")
    media_file = MediaFile(
        disk_id=disk.id, relative_path="media/movies/Movie.2024.mkv", size_bytes=7,
        st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(media_file)
    db_session.commit()
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="Movie.2024.mkv",
        size_bytes=7, source="catalog_search", direction="media_to_torrent", confidence=1.0,
        download_link="https://t.example/dl/1", file_list_json='["Movie.2024.mkv"]', folder=folder,
    )
    db_session.add(candidate)
    db_session.commit()
    review = MatchReview(candidate_id=candidate.id, media_file_id=media_file.id, status="approved")
    db_session.add(review)
    db_session.commit()
    return root, review


def test_a_client_that_creates_subfolders_gets_the_file_inside_its_folder(db_session, tmp_path):
    # Il caso segnalato: qBittorrent con "Crea sottocartella" cercava il file
    # in torrents/Movie.2024/, l'hardlink era in torrents/ e partiva il download.
    root, review = _movie_review(db_session, tmp_path)
    adapter = LayoutAdapter("Subfolder")

    executor.execute_review(db_session, review, adapter)

    assert (root / "torrents" / "Movie.2024" / "Movie.2024.mkv").is_file()
    assert not (root / "torrents" / "Movie.2024.mkv").exists()
    assert adapter.add_torrent_calls[0]["save_path"] == str(root / "torrents" / "Movie.2024")
    assert adapter.add_torrent_calls[0]["layout"] == "Original"


def test_without_subfolders_the_root_folder_of_the_torrent_is_left_out(db_session, tmp_path):
    root, review = _movie_review(db_session, tmp_path, folder="Release.Name")
    adapter = LayoutAdapter("NoSubfolder")

    executor.execute_review(db_session, review, adapter)

    assert (root / "torrents" / "Movie.2024.mkv").is_file()
    call = adapter.add_torrent_calls[0]
    assert (call["save_path"], call["layout"]) == (str(root / "torrents"), "NoSubfolder")


def test_a_torrent_with_its_own_folder_ignores_the_subfolder_preference(db_session, tmp_path):
    root, review = _movie_review(db_session, tmp_path, folder="Release.Name")
    adapter = LayoutAdapter("Subfolder")

    executor.execute_review(db_session, review, adapter)

    assert (root / "torrents" / "Release.Name" / "Movie.2024.mkv").is_file()
    assert adapter.add_torrent_calls[0]["save_path"] == str(root / "torrents")
    assert adapter.add_torrent_calls[0]["layout"] == "Original"


def test_execute_media_to_torrent_respects_candidate_folder(db_session, tmp_path):
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    media_file_path = root / "media" / "movies" / "Movie.2024.mkv"
    media_file_path.write_bytes(b"content")
    media_file = MediaFile(
        disk_id=disk.id, relative_path="media/movies/Movie.2024.mkv", size_bytes=7,
        st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(media_file)
    db_session.commit()
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="Movie.2024.mkv",
        size_bytes=7, source="catalog_search", direction="media_to_torrent", confidence=1.0,
        download_link="https://t.example/dl/1", file_list_json='["Movie.2024.mkv"]', folder="Release.Name",
    )
    db_session.add(candidate)
    db_session.commit()
    match_review = MatchReview(candidate_id=candidate.id, media_file_id=media_file.id, status="approved")
    db_session.add(match_review)
    db_session.commit()

    executor.execute_review(db_session, match_review, FakeAdapter())

    assert (root / "torrents" / "Release.Name" / "Movie.2024.mkv").is_file()


def test_execute_media_to_torrent_fails_on_cross_device(db_session, tmp_path, monkeypatch):
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    media_file_path = root / "media" / "movies" / "Movie.2024.mkv"
    media_file_path.write_bytes(b"content")
    media_file = MediaFile(
        disk_id=disk.id, relative_path="media/movies/Movie.2024.mkv", size_bytes=7,
        st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(media_file)
    db_session.commit()
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="Movie.2024.mkv",
        size_bytes=7, source="catalog_search", direction="media_to_torrent", confidence=1.0,
        download_link="https://t.example/dl/1", file_list_json='["Movie.2024.mkv"]',
    )
    db_session.add(candidate)
    db_session.commit()
    match_review = MatchReview(candidate_id=candidate.id, media_file_id=media_file.id, status="approved")
    db_session.add(match_review)
    db_session.commit()

    real_stat = os.stat

    def fake_stat(path, *a, **kw):
        result = real_stat(path, *a, **kw)
        if str(path) == str(media_file_path):
            # os.path.isfile() (chiamato prima dei controlli di hardlinks.check_link) usa
            # anche st_mode: serve un os.stat_result completo, non un oggetto
            # con solo st_dev, altrimenti fallisce lì invece che dove vogliamo.
            seq = list(result)
            seq[2] = result.st_dev + 1  # indice 2 = st_dev nella sequenza stat_result
            return os.stat_result(seq)
        return result

    monkeypatch.setattr(executor.os, "stat", fake_stat)

    with pytest.raises(executor.ExecutionError, match="different devices"):
        executor.execute_review(db_session, match_review, FakeAdapter())


def test_execute_torrent_to_client_adds_existing_file_without_new_hardlink(db_session, tmp_path):
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    existing_file = root / "torrents" / "Standalone.2024.mkv"
    existing_file.write_bytes(b"content")
    media_file = MediaFile(
        disk_id=disk.id, relative_path="media/movies/Standalone.2024.mkv", size_bytes=7,
        st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(media_file)
    db_session.commit()
    seed_file = SeedFile(
        disk_id=disk.id, relative_path="torrents/Standalone.2024.mkv", size_bytes=7, st_dev=1, inode=2,
        media_file_id=media_file.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(seed_file)
    db_session.commit()
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="Standalone.2024.mkv",
        size_bytes=7, source="catalog_search", direction="torrent_to_client", confidence=1.0,
        download_link="https://t.example/dl/1",
    )
    db_session.add(candidate)
    db_session.commit()
    match_review = MatchReview(candidate_id=candidate.id, seed_file_id=seed_file.id, status="approved")
    db_session.add(match_review)
    db_session.commit()

    adapter = FakeAdapter()
    seed_job = executor.execute_review(db_session, match_review, adapter)

    assert seed_job.hardlink_created_at is None  # nessun nuovo hardlink, il file c'era già
    assert seed_job.info_hash == "deadbeef"
    assert adapter.add_torrent_calls[0]["save_path"] == str(root / "torrents")


def test_execute_without_download_link_fails_explicitly(db_session, tmp_path):
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    existing_file = root / "torrents" / "Standalone.2024.mkv"
    existing_file.write_bytes(b"content")
    media_file = MediaFile(
        disk_id=disk.id, relative_path="media/movies/x.mkv", size_bytes=7,
        st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(media_file)
    db_session.commit()
    seed_file = SeedFile(
        disk_id=disk.id, relative_path="torrents/Standalone.2024.mkv", size_bytes=7, st_dev=1, inode=2,
        media_file_id=media_file.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(seed_file)
    db_session.commit()
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x",
        size_bytes=7, source="catalog_search", direction="torrent_to_client", confidence=1.0,
        download_link=None,
    )
    db_session.add(candidate)
    db_session.commit()
    match_review = MatchReview(candidate_id=candidate.id, seed_file_id=seed_file.id, status="approved")
    db_session.add(match_review)
    db_session.commit()

    with pytest.raises(executor.ExecutionError, match="download_link"):
        executor.execute_review(db_session, match_review, FakeAdapter())


def test_reconcile_seed_job_updates_status_to_seeding(db_session, tmp_path):
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x", size_bytes=1,
        source="catalog_search", direction="media_to_torrent", confidence=1.0,
    )
    db_session.add(candidate)
    db_session.commit()
    from nazgarr.core.models import SeedJob

    seed_job = SeedJob(
        candidate_id=candidate.id, final_status="in_progress", info_hash="deadbeef", recheck_status="pending"
    )
    db_session.add(seed_job)
    db_session.commit()

    executor.reconcile_seed_job(db_session, seed_job, FakeAdapter(recheck_status="ok"))

    assert seed_job.final_status == "seeding"


def test_add_torrent_uses_per_client_root_path_override(db_session, tmp_path):
    # Il motivo per cui l'override vive su (disk, torrent_client) e non sul
    # disco: due client diversi sullo stesso disco possono vederlo montato
    # a path diversi nei rispettivi container — qui solo uno dei due ha un
    # override, l'altro deve continuare a vedere il path locale invariato.
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    media_file_path = root / "media" / "movies" / "Movie.2024.mkv"
    media_file_path.write_bytes(b"content")
    media_file = MediaFile(
        disk_id=disk.id, relative_path="media/movies/Movie.2024.mkv", size_bytes=7,
        st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(media_file)
    db_session.commit()
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="Movie.2024.mkv",
        size_bytes=7, source="catalog_search", direction="media_to_torrent", confidence=1.0,
        download_link="https://t.example/dl/1", file_list_json='["Movie.2024.mkv"]',
    )
    db_session.add(candidate)
    db_session.commit()

    tc_with_override = TorrentClient(label="qbt-a", adapter_type="qbittorrent", base_url="http://a")
    tc_without_override = TorrentClient(label="qbt-b", adapter_type="qbittorrent", base_url="http://b")
    db_session.add_all([tc_with_override, tc_without_override])
    db_session.commit()
    db_session.add(DiskTorrentClient(
        disk_id=disk.id, torrent_client_id=tc_with_override.id, torrent_client_root_path="/downloads",
    ))
    db_session.commit()

    match_review_a = MatchReview(candidate_id=candidate.id, media_file_id=media_file.id, status="approved")
    db_session.add(match_review_a)
    db_session.commit()
    adapter_a = FakeAdapter()
    executor.execute_review(db_session, match_review_a, adapter_a, tc_with_override.id)
    assert adapter_a.add_torrent_calls[0]["save_path"] == "/downloads/torrents"

    candidate_b = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="2", name="Movie.2024.mkv",
        size_bytes=7, source="catalog_search", direction="torrent_to_client", confidence=1.0,
        download_link="https://t.example/dl/2",
    )
    db_session.add(candidate_b)
    db_session.commit()
    seed_file = SeedFile(
        disk_id=disk.id, relative_path="torrents/Movie.2024.mkv", size_bytes=7, st_dev=1, inode=2,
        media_file_id=media_file.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(seed_file)
    db_session.commit()
    match_review_b = MatchReview(candidate_id=candidate_b.id, seed_file_id=seed_file.id, status="approved")
    db_session.add(match_review_b)
    db_session.commit()
    adapter_b = FakeAdapter()
    executor.execute_review(db_session, match_review_b, adapter_b, tc_without_override.id)
    assert adapter_b.add_torrent_calls[0]["save_path"] == str(root / "torrents")


def _single_file_review(db_session, root, disk, tracker, item, run):
    media_file_path = root / "media" / "movies" / "Movie.2024.mkv"
    media_file_path.write_bytes(b"content")
    media_file = MediaFile(
        disk_id=disk.id, relative_path="media/movies/Movie.2024.mkv", size_bytes=7,
        st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(media_file)
    db_session.commit()
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="2", name="Movie.2024.mkv",
        size_bytes=7, source="catalog_search", direction="media_to_torrent", confidence=1.0,
        download_link="https://t.example/dl/2", file_list_json='["Movie.2024.mkv"]',
    )
    db_session.add(candidate)
    db_session.commit()
    match_review = MatchReview(candidate_id=candidate.id, media_file_id=media_file.id, status="approved")
    db_session.add(match_review)
    db_session.commit()
    return media_file_path, match_review


def test_a_cross_seed_reuses_the_hardlink_already_there(db_session, tmp_path):
    # La stessa release, con lo stesso nome, già in seed per un altro tracker:
    # lo stesso inode si riusa invece di fallire.
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    media_file_path, match_review = _single_file_review(db_session, root, disk, tracker, item, run)
    existing = root / "torrents" / "Movie.2024.mkv"
    os.link(media_file_path, existing)

    adapter = FakeAdapter()
    seed_job = executor.execute_review(db_session, match_review, adapter)

    assert os.path.samefile(media_file_path, existing)
    assert seed_job.info_hash == "deadbeef" and len(adapter.add_torrent_calls) == 1


def test_another_file_at_the_destination_is_never_overwritten(db_session, tmp_path):
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    _media_file_path, match_review = _single_file_review(db_session, root, disk, tracker, item, run)
    (root / "torrents" / "Movie.2024.mkv").write_bytes(b"something else")

    with pytest.raises(executor.ExecutionError, match="already exists"):
        executor.execute_review(db_session, match_review, FakeAdapter())
    assert (root / "torrents" / "Movie.2024.mkv").read_bytes() == b"something else"


@pytest.mark.parametrize("target", ["outside", "inside"])
def test_a_library_file_replaced_by_a_symlink_is_never_linked(db_session, tmp_path, target):
    # Fra la scansione e l'esecuzione il file in libreria è diventato un
    # link simbolico (fuori dal disco o anche dentro): niente hardlink, e
    # niente torrent nel client.
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    media_file_path, match_review = _single_file_review(db_session, root, disk, tracker, item, run)
    elsewhere = (tmp_path / "secret.mkv") if target == "outside" else (root / "media" / "other.mkv")
    elsewhere.write_bytes(b"content")
    media_file_path.unlink()
    media_file_path.symlink_to(elsewhere)

    adapter = FakeAdapter()
    with pytest.raises(executor.ExecutionError, match="scope|symbolic link"):
        executor.execute_review(db_session, match_review, adapter)
    assert not os.path.lexists(root / "torrents" / "Movie.2024.mkv")
    assert adapter.add_torrent_calls == []


@pytest.mark.parametrize("can_skip", [True, False])
def test_the_recheck_is_skipped_only_by_a_client_that_can(can_skip):
    from types import SimpleNamespace

    class Adapter:
        can_skip_recheck = can_skip

        def add_torrent(self, url, save_path, force_recheck=True, expected_info_hash=None, **kwargs):
            self.kwargs = kwargs
            return "h1"

    adapter, seed_job = Adapter(), SimpleNamespace(recheck_skipped=None)
    torrent = executor._CheckedTorrent(content=_movie_torrent(), info_hash="h1")

    executor._add_to_client(adapter, torrent, "/torrents", seed_job, skip_recheck=True)

    # Transmission e rTorrent ricontrollano comunque: il seed job non lo registra come saltato.
    assert adapter.kwargs == ({"skip_check_verified": True} if can_skip else {})
    assert seed_job.recheck_skipped is (True if can_skip else None)


def test_a_torrent_stopped_after_a_good_recheck_is_started(db_session, tmp_path):
    # qBittorrent con la condizione di arresto "file controllati" (qui non la
    # lascia cambiare all'aggiunta): il recheck riesce e il torrent resta fermo.
    _root, review = _movie_review(db_session, tmp_path)

    class StopsAfterCheck(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.started = []

        def get_torrent_status(self, info_hash):
            return TorrentStatus(info_hash=info_hash, state="stoppedUP", recheck_status="ok", progress=1.0)

        def start(self, info_hash):
            self.started.append(info_hash)

    adapter = StopsAfterCheck()
    seed_job = executor.execute_review(db_session, review, adapter)
    executor.reconcile_seed_job(db_session, seed_job, adapter)

    assert seed_job.final_status == "seeding"
    assert adapter.started == ["deadbeef"]


def test_a_reseed_uses_the_client_labels_chosen_on_its_review(db_session, tmp_path):
    from nazgarr.reseed import review as review_module

    _root, review = _movie_review(db_session, tmp_path)
    client = TorrentClient(label="qb", adapter_type="qbittorrent", base_url="http://qb.test", category_movie="film",
                           tags_reseed="nazgarr,reseed")
    db_session.add(client)
    db_session.commit()

    class LabelAdapter(FakeAdapter):
        def add_torrent(self, torrent_file_or_url, save_path, force_recheck=True, expected_info_hash=None,
                        category=None, tags=None):
            self.add_torrent_calls.append({"category": category, "tags": tags})
            return self.info_hash

    # Scelti a mano come per un upload: vincono sui default del client.
    review_module.set_client_labels(db_session, review, "4k-movies", " cross , mine ")
    adapter = LabelAdapter()
    executor.execute_review(db_session, review, adapter, client.id)
    assert adapter.add_torrent_calls[0] == {"category": "4k-movies", "tags": ["cross", "mine"]}


def test_without_a_choice_a_reseed_takes_the_client_defaults_and_empty_means_none(db_session, tmp_path):
    from nazgarr.reseed import review as review_module

    _root, review = _movie_review(db_session, tmp_path)
    client = TorrentClient(label="qb", adapter_type="qbittorrent", base_url="http://qb.test", category_movie="film",
                           tags_reseed="reseed")
    db_session.add(client)
    db_session.commit()

    labels = executor._labels(db_session, client.id, review.candidate, review)
    assert labels == {"category": "film", "tags": ["reseed"]}
    review_module.set_client_labels(db_session, review, "", None)  # nessuna categoria, i tag di sempre
    assert executor._labels(db_session, client.id, review.candidate, review) == {"tags": ["reseed"]}


def _failed_recheck_job(db_session, tmp_path):
    from nazgarr.core.models import SeedJob

    _root, disk, tracker, item, _run = _base_setup(db_session, tmp_path)
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x", size_bytes=1,
        source="catalog_search", direction="media_to_torrent", confidence=1.0,
    )
    db_session.add(candidate)
    db_session.commit()
    seed_job = SeedJob(candidate_id=candidate.id, final_status="in_progress", info_hash="deadbeef",
                       recheck_status="pending")
    db_session.add(seed_job)
    db_session.commit()
    return seed_job


class _IncompleteAfterRecheck(FakeAdapter):
    def __init__(self, state="stalledDL", stop_error=None):
        super().__init__()
        self.state, self.stop_error, self.stopped = state, stop_error, []

    def get_torrent_status(self, info_hash):
        return TorrentStatus(info_hash=info_hash, state=self.state, recheck_status="failed", progress=0.97,
                             incomplete=True, amount_left=1000)

    def stop(self, info_hash):
        if self.stop_error is not None:
            raise self.stop_error
        self.stopped.append(info_hash)


def test_a_failed_recheck_is_stopped_when_it_is_reconciled(db_session, tmp_path):
    # Avviato, il client scaricava i piece mancanti negli hardlink: gli stessi
    # byte dei file in libreria, senza alcuna approvazione. Lo stop arriva al
    # reconcile, non alla fine del recheck: fino ad allora il torrent gira
    # (docs/SPEC.md §5, la finestra è una decisione aperta).
    seed_job = _failed_recheck_job(db_session, tmp_path)
    adapter = _IncompleteAfterRecheck()

    executor.reconcile_seed_job(db_session, seed_job, adapter)

    assert seed_job.final_status == "failed" and adapter.stopped == ["deadbeef"]
    assert "stopped in the client" in seed_job.error_message


def test_a_torrent_already_stopped_is_not_stopped_again(db_session, tmp_path):
    seed_job = _failed_recheck_job(db_session, tmp_path)
    adapter = _IncompleteAfterRecheck(state="stoppedDL")

    executor.reconcile_seed_job(db_session, seed_job, adapter)

    assert seed_job.final_status == "failed" and adapter.stopped == []


@pytest.mark.parametrize("error,expected", [
    (NotImplementedError(), "cannot be told to stop it"), (RuntimeError("down"), "could not be stopped"),
])
def test_a_torrent_that_cannot_be_stopped_says_to_stop_it_by_hand(db_session, tmp_path, error, expected):
    seed_job = _failed_recheck_job(db_session, tmp_path)

    executor.reconcile_seed_job(db_session, seed_job, _IncompleteAfterRecheck(stop_error=error))

    assert seed_job.final_status == "failed"
    assert expected in seed_job.error_message and "by hand" in seed_job.error_message


def test_a_plugin_adapter_without_stop_keeps_the_safe_default():
    from nazgarr.sdk import TorrentClientAdapter

    class Plugin(TorrentClientAdapter):
        def add_torrent(self, *a, **kw):
            return "h"

        def get_torrent_status(self, info_hash):
            raise NotImplementedError

        def list_torrents(self, on_progress=None):
            return []

    with pytest.raises(NotImplementedError):
        Plugin().stop("h")


def test_the_client_gets_the_bytes_nazgarr_downloaded_never_the_tracker_link(db_session, tmp_path, _tracker_torrent):
    # Con il link il client scaricava la sua copia: un tracker ostile poteva
    # servire a Nazgarr il torrent giusto e al client un altro.
    _root, review = _movie_review(db_session, tmp_path)
    adapter = FakeAdapter()

    executor.execute_review(db_session, review, adapter)

    call = adapter.add_torrent_calls[0]
    assert call["url"] != "https://t.example/dl/1" and call["content"] == _movie_torrent()
    assert call["expected"] == compute_info_hash(_movie_torrent())
    assert _tracker_torrent["links"] == ["https://t.example/dl/1"]
    assert review.candidate.info_hash == compute_info_hash(_movie_torrent())  # per l'attesa e i retry
    assert not os.path.exists(call["url"])  # il file temporaneo non resta


def test_a_tracker_serving_another_torrent_than_the_matched_one_gets_nothing(db_session, tmp_path, _tracker_torrent):
    root, review = _movie_review(db_session, tmp_path)
    review.candidate.info_hash = compute_info_hash(_movie_torrent())  # letto dal matching o dal controllo
    db_session.commit()
    _tracker_torrent["content"] = _movie_torrent(b"CONTENT")  # stessi nomi, altri piece
    adapter = FakeAdapter()

    with pytest.raises(executor.ExecutionError, match="different .torrent"):
        executor.execute_review(db_session, review, adapter)

    assert adapter.add_torrent_calls == []
    assert not (root / "torrents" / "Movie.2024.mkv").exists()  # nessun hardlink prima del controllo
    from nazgarr.core.models import SeedJob
    job = db_session.query(SeedJob).one()
    assert job.final_status == "failed" and "different .torrent" in job.error_message


def test_a_torrent_that_cannot_be_downloaded_is_a_failed_job_to_retry(db_session, tmp_path, monkeypatch):
    root, review = _movie_review(db_session, tmp_path)

    def down(candidate):
        raise executor.ExecutionError("Could not download the .torrent from t: tracker down")

    monkeypatch.setattr(executor, "_download_torrent", down)
    adapter = FakeAdapter()

    with pytest.raises(executor.ExecutionError, match="tracker down"):
        executor.execute_review(db_session, review, adapter)

    from nazgarr.core.models import SeedJob
    job = db_session.query(SeedJob).one()
    assert (job.final_status, job.info_hash) == ("failed", None)  # visibile fra le esecuzioni fallite
    assert adapter.add_torrent_calls == [] and not (root / "torrents" / "Movie.2024.mkv").exists()


def test_a_download_link_that_is_a_local_path_is_never_read_or_sent(db_session, tmp_path, _tracker_torrent):
    # Gli adapter mandano per contenuto un file locale: un link del tracker come
    # /proc/self/environ veniva letto e spedito al client.
    _root, review = _movie_review(db_session, tmp_path)
    secret = tmp_path / "secret.env"
    secret.write_bytes(b"APP_SECRET_KEY=hunter2")
    review.candidate.download_link = str(secret)
    db_session.commit()
    adapter = FakeAdapter()

    executor.execute_review(db_session, review, adapter)

    assert adapter.add_torrent_calls[0]["content"] == _movie_torrent()
    assert _tracker_torrent["links"] == [str(secret)]  # chiesto al tracker, mai aperto qui


class _ClientDown(FakeAdapter):
    def add_torrent(self, *a, **kw):
        raise RuntimeError("client down")

    def get_torrent_info(self, info_hash):
        return None  # risponde: quel torrent non ce l'ha


def test_a_single_file_add_that_fails_removes_only_the_hardlink_it_created(db_session, tmp_path):
    # Prima il percorso a file singolo lasciava l'hardlink, quello dei pack
    # lo toglieva: ora una regola sola.
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    media_file_path, review = _single_file_review(db_session, root, disk, tracker, item, run)

    with pytest.raises(executor.ExecutionError, match="client down"):
        executor.execute_review(db_session, review, _ClientDown())

    assert not (root / "torrents" / "Movie.2024.mkv").exists()
    assert media_file_path.read_bytes() == b"content"  # il file in libreria non si tocca mai


def test_a_reused_hardlink_stays_when_the_add_fails(db_session, tmp_path):
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    media_file_path, review = _single_file_review(db_session, root, disk, tracker, item, run)
    os.link(media_file_path, root / "torrents" / "Movie.2024.mkv")  # un cross-seed già in seed

    with pytest.raises(executor.ExecutionError):
        executor.execute_review(db_session, review, _ClientDown())

    assert os.path.samefile(media_file_path, root / "torrents" / "Movie.2024.mkv")


def test_a_seed_file_linked_outside_the_disk_is_refused_before_the_client(db_session, tmp_path):
    root, disk, tracker, item, run = _base_setup(db_session, tmp_path)
    outside = tmp_path / "elsewhere.mkv"
    outside.write_bytes(b"content")
    (root / "torrents" / "Standalone.2024.mkv").symlink_to(outside)
    seed_file = SeedFile(
        disk_id=disk.id, relative_path="torrents/Standalone.2024.mkv", size_bytes=7, st_dev=1, inode=2,
        last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(seed_file)
    db_session.commit()
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="Standalone.2024.mkv",
        size_bytes=7, source="catalog_search", direction="torrent_to_client", confidence=1.0,
        download_link="https://t.example/dl/1",
    )
    db_session.add(candidate)
    db_session.commit()
    review = MatchReview(candidate_id=candidate.id, seed_file_id=seed_file.id, status="approved")
    db_session.add(review)
    db_session.commit()
    adapter = FakeAdapter()

    with pytest.raises(executor.ExecutionError, match="scope"):
        executor.execute_review(db_session, review, adapter)
    assert adapter.add_torrent_calls == []


class _DownloadingTracker:
    def __init__(self, result):
        self.result = result
        self.links = []

    def download_torrent(self, url):
        self.links.append(url)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _with_tracker_adapter(monkeypatch, fake):
    from contextlib import contextmanager

    from nazgarr.integrations import adapter_factory

    @contextmanager
    def tracker(row):
        yield fake

    monkeypatch.setattr(adapter_factory, "tracker", tracker)


def test_the_real_download_goes_through_the_candidates_tracker_adapter(monkeypatch):
    # Il fixture autouse sostituisce _download_torrent in ogni altro test.
    fake = _DownloadingTracker(b"d4:infod4:name1:xee")
    _with_tracker_adapter(monkeypatch, fake)
    link = "https://t.example/torrent/download/1.abcdef"
    candidate = Candidate(tracker=Tracker(label="t", adapter_type="unit3d", base_url="https://t.example"),
                          download_link=link)

    assert _REAL_DOWNLOAD_TORRENT(candidate) == b"d4:infod4:name1:xee"
    assert fake.links == [link]


def test_a_tracker_without_download_torrent_or_a_failed_download_is_an_execution_error(monkeypatch):
    from nazgarr.sdk import NotSupportedError

    # Un plugin senza download_torrent (ora serve ai reseed, docs/SDK.md), e
    # un errore che porta il link con la chiave: mai salvata in chiaro.
    tracker = Tracker(label="Plugin tracker", adapter_type="plugin", base_url="https://t.example")
    for error, expected in (
        (NotSupportedError("MyTracker non supporta download_torrent()"), "non supporta download_torrent"),
        (RuntimeError("GET https://t.example/torrent/download/7.secretkey123 failed"), "7.<redacted> failed"),
    ):
        _with_tracker_adapter(monkeypatch, _DownloadingTracker(error))
        candidate = Candidate(tracker=tracker, download_link="https://t.example/torrent/download/7.secretkey123")
        with pytest.raises(executor.ExecutionError) as info:
            _REAL_DOWNLOAD_TORRENT(candidate)
        assert str(info.value).startswith("Could not download the .torrent from Plugin tracker: ")
        assert expected in str(info.value) and "secretkey123" not in str(info.value)


def test_a_candidate_whose_tracker_is_gone_cannot_be_downloaded(monkeypatch):
    fake = _DownloadingTracker(b"never")
    _with_tracker_adapter(monkeypatch, fake)

    with pytest.raises(executor.ExecutionError, match="tracker no longer exists"):
        _REAL_DOWNLOAD_TORRENT(Candidate(tracker=None, download_link="https://t.example/torrent/download/1.k"))
    assert fake.links == []


def _catalog_only_review(db_session, tmp_path):
    """Un candidato a file singolo il cui .torrent il matching non ha letto:
    cartella e nome solo dal catalogo, nessun info hash."""
    from nazgarr.core.models import CandidateFile

    root, review = _movie_review(db_session, tmp_path)
    review.candidate.files = [CandidateFile(torrent_path="Movie.2024.mkv", size_bytes=7, is_video=True,
                                            media_file_id=review.media_file_id)]
    db_session.commit()
    return root, review


def _folder_torrent(name: str, folder: str = "Movie.2024.1080p-GRP") -> bytes:
    return _bencode({"info": {"name": folder, "piece length": 16, "pieces": hashlib.sha1(b"content").digest(),
                              "files": [{"length": 7, "path": [name]}]}})


def test_a_catalogue_only_structure_takes_the_folder_from_the_torrent_before_any_hardlink(
        db_session, tmp_path, _tracker_torrent):
    # Con la verifica spenta, cartella e nomi del catalogo arrivavano fino agli
    # hardlink (audit 2026-10-18, finding 146).
    root, review = _catalog_only_review(db_session, tmp_path)
    _tracker_torrent["content"] = _folder_torrent("Movie.2024.mkv")
    adapter = FakeAdapter(info_hash=compute_info_hash(_tracker_torrent["content"]))

    executor.execute_review(db_session, review, adapter)

    assert (root / "torrents" / "Movie.2024.1080p-GRP" / "Movie.2024.mkv").is_file()
    assert review.candidate.folder == "Movie.2024.1080p-GRP"
    assert len(_tracker_torrent["links"]) == 1  # scaricato una volta sola


def test_a_catalogue_name_the_torrent_does_not_have_creates_nothing(db_session, tmp_path, _tracker_torrent):
    root, review = _catalog_only_review(db_session, tmp_path)
    _tracker_torrent["content"] = _folder_torrent("Something.Else.mkv")
    adapter = FakeAdapter()

    with pytest.raises(executor.ExecutionError, match="not the ones the tracker's catalogue listed"):
        executor.execute_review(db_session, review, adapter)

    assert not any((root / "torrents").rglob("*.mkv"))
    assert adapter.add_torrent_calls == []


def test_a_known_info_hash_does_not_skip_the_structure_check(db_session, tmp_path, _tracker_torrent):
    # Il controllo completo impara l'info hash e ritrova i file anche per
    # nome: prima, con l'info hash noto, gli hardlink seguivano lo stesso i
    # nomi del catalogo. Conta se la struttura è mai stata letta da un .torrent.
    root, review = _catalog_only_review(db_session, tmp_path)
    _tracker_torrent["content"] = _folder_torrent("Something.Else.mkv")
    review.candidate.info_hash = compute_info_hash(_tracker_torrent["content"])
    db_session.commit()
    adapter = FakeAdapter(info_hash=review.candidate.info_hash)

    with pytest.raises(executor.ExecutionError, match="not the ones the tracker's catalogue listed"):
        executor.execute_review(db_session, review, adapter)

    assert not any((root / "torrents").rglob("*.mkv"))
    assert adapter.add_torrent_calls == []


def test_an_execution_error_carries_the_english_text_never_the_bare_code(db_session, tmp_path, monkeypatch):
    # Il retry mostrava "Retry failed: client_cannot_see_path", senza percorso,
    # mentre il seed_job aveva il testo giusto (audit 2026-10-18, finding 119).
    from nazgarr.core.models import SeedJob
    from nazgarr.torrents.client_paths import ClientPathError

    _root, review = _catalog_only_review(db_session, tmp_path)

    def cannot_see(*args):
        raise ClientPathError("client_cannot_see_path", path="/data/torrents", folder="/data/media",
                              client_root="/downloads")

    monkeypatch.setattr(executor, "client_visible_path", cannot_see)
    with pytest.raises(executor.ExecutionError) as info:
        executor.execute_review(db_session, review, FakeAdapter())

    assert str(info.value).startswith("The client cannot see /data/torrents")
    assert str(info.value) == db_session.query(SeedJob).one().error_message
