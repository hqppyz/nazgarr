"""Matching incrementale (nazgarr/matching.py): un orfano già cercato non viene
ricercato finché non cambia o non passa rematch_interval_days, i file
esclusi non vengono mai cercati, un errore su un file non ferma gli altri
e un rate limit persistente ferma il tracker per il resto della run."""

from datetime import UTC, datetime, timedelta

from nazgarr import matching, pipeline, review, settings_repo
from nazgarr.adapters.tracker.base import TorrentCandidate, TrackerRateLimitedError
from nazgarr.models import Candidate, Disk, MatchAttempt, MatchReview, MediaFile, MediaItem, Tracker


def _tc(**overrides) -> TorrentCandidate:
    defaults = dict(
        torrent_id_remote="1", info_hash=None, name="Movie.2024.mkv", size_bytes=1000,
        file_list=["Movie.2024.mkv"], mediainfo_unique_id=None, download_link=None,
    )
    defaults.update(overrides)
    return TorrentCandidate(**defaults)


class CountingTracker:
    def __init__(self, candidates=None, fail_on=None, rate_limit_on=None):
        self.calls = 0
        self._candidates = candidates or []
        self._fail_on = fail_on
        self._rate_limit_on = rate_limit_on

    def search_by_tmdb(self, tmdb_id):
        self.calls += 1
        if self._rate_limit_on is not None and self.calls >= self._rate_limit_on:
            raise TrackerRateLimitedError("429")
        if self._fail_on == self.calls:
            raise RuntimeError("boom")
        return self._candidates


def _setup(db_session, paths=("movies/a.mkv",), size=1000):
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    disk = Disk(label="d", root_path="/mnt/d", media_rel_path="movies")
    db_session.add_all([tracker, disk])
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    item = MediaItem(content_type="movie", tmdb_id=42)
    db_session.add(item)
    db_session.commit()
    files = []
    for i, path in enumerate(paths):
        mf = MediaFile(
            disk_id=disk.id, relative_path=path, size_bytes=size, st_dev=1, inode=100 + i,
            media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        )
        db_session.add(mf)
        files.append(mf)
    db_session.commit()
    return tracker, files


def test_second_run_skips_orphans_already_searched(db_session, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    tracker, _ = _setup(db_session, paths=("movies/a.mkv", "movies/b.mkv"))
    adapter = CountingTracker()

    first = matching.run_media_to_torrent_matching(db_session, tracker, adapter)
    second = matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    assert first["files"] == 2
    assert second["files"] == 0
    assert second["skipped_fresh"] == 2
    assert adapter.calls == 2
    assert db_session.query(MatchAttempt).count() == 2


def test_orphan_is_searched_again_when_its_size_changes(db_session, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    tracker, (mf,) = _setup(db_session)
    adapter = CountingTracker()
    matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    mf.size_bytes = 2000
    db_session.commit()
    totals = matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    assert totals["files"] == 1
    assert adapter.calls == 2


def test_orphan_is_searched_again_after_the_interval(db_session, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    tracker, _ = _setup(db_session)
    adapter = CountingTracker()
    matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    attempt = db_session.query(MatchAttempt).one()
    attempt.attempted_at = datetime.now(UTC) - timedelta(days=8)
    db_session.commit()
    matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    assert adapter.calls == 2


def test_interval_zero_searches_on_every_run(db_session, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    tracker, _ = _setup(db_session)
    settings_repo.set_setting(db_session, "rematch_interval_days", "0")
    adapter = CountingTracker()

    matching.run_media_to_torrent_matching(db_session, tracker, adapter)
    matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    assert adapter.calls == 2


def test_excluded_orphans_are_never_searched(db_session, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    tracker, _ = _setup(db_session, paths=("movies/a.mkv", "movies/Movie/sample/a-sample.mkv"))
    settings_repo.set_setting(db_session, "exclusion_patterns", "sample/*")
    adapter = CountingTracker()

    totals = matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    assert totals["files"] == 1
    assert adapter.calls == 1


def test_a_failing_file_does_not_stop_the_others_and_is_retried_next_run(db_session, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    tracker, _ = _setup(db_session, paths=("movies/a.mkv", "movies/b.mkv"))
    adapter = CountingTracker(fail_on=1)

    first = matching.run_media_to_torrent_matching(db_session, tracker, adapter)
    second = matching.run_media_to_torrent_matching(db_session, tracker, CountingTracker())

    assert first == {
        "files": 1, "from_history": 0, "candidates": 0, "skipped_fresh": 0, "failed": 1, "rate_limited": False,
    }
    # Il file fallito non ha un match_attempt: viene ricercato, l'altro no.
    assert second["files"] == 1
    assert second["skipped_fresh"] == 1


def test_rate_limit_stops_the_tracker_for_the_rest_of_the_run(db_session, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    tracker, _ = _setup(db_session, paths=("movies/a.mkv", "movies/b.mkv", "movies/c.mkv"))
    adapter = CountingTracker(rate_limit_on=2)

    totals = matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    assert totals["rate_limited"] is True
    assert totals["files"] == 1
    assert adapter.calls == 2  # mai una terza chiamata dopo il 429
    assert db_session.query(MatchAttempt).count() == 1


def test_user_rejected_torrent_is_not_proposed_again(db_session, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    settings_repo.set_setting(db_session, "rematch_interval_days", "0")
    tracker, (mf,) = _setup(db_session)
    adapter = CountingTracker(candidates=[_tc(torrent_id_remote="7", size_bytes=1000)])

    matching.run_media_to_torrent_matching(db_session, tracker, adapter)
    first_review = db_session.query(MatchReview).one()
    review.reject(db_session, first_review)

    matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    assert db_session.query(MatchReview).count() == 1
    # Il candidato resta comunque nell'audit trail.
    assert db_session.query(Candidate).filter_by(torrent_id_remote="7").count() == 2


def test_system_superseded_review_does_not_block_the_same_torrent(db_session, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    settings_repo.set_setting(db_session, "rematch_interval_days", "0")
    tracker, _ = _setup(db_session)
    adapter = CountingTracker(candidates=[_tc(torrent_id_remote="7", size_bytes=1000)])

    matching.run_media_to_torrent_matching(db_session, tracker, adapter)
    matching.run_media_to_torrent_matching(db_session, tracker, adapter)

    statuses = sorted(r.status for r in db_session.query(MatchReview).all())
    assert statuses == ["pending", "rejected"]


def test_pipeline_records_rate_limit_and_skips_the_other_direction(db_session, monkeypatch, tmp_path):
    from nazgarr import adapter_factory

    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    _setup(db_session)
    adapter = CountingTracker(rate_limit_on=1)
    monkeypatch.setattr(adapter_factory, "build_tracker_adapter", lambda row: adapter)
    t2c_calls = []
    monkeypatch.setattr(matching, "run_torrent_to_client_matching", lambda *a: t2c_calls.append(a))

    run = pipeline.start_run(db_session, "manual")
    pipeline.run_bulk_import(db_session, run, str(tmp_path))

    assert t2c_calls == []
    assert run.finished_at is not None
    assert run.errors >= 1
    assert "rate limit" in run.last_error


def test_torrent_to_client_matching_is_skipped_when_no_client_file_is_linked(db_session, monkeypatch, tmp_path):
    """Disco non associato al client (o percorsi diversi): ogni file lato
    torrent risulterebbe orfano, e cercarli tutti sul tracker costerebbe ore
    per file già in seed — il caso reale che ha rallentato una run."""
    from nazgarr import adapter_factory
    from nazgarr.adapters.torrent_client.base import ClientTorrentFileInfo, ClientTorrentInfo
    from nazgarr.models import SeedFile, TorrentClient

    tracker, _ = _setup(db_session)
    run0 = pipeline.start_run(db_session, "manual")
    db_session.add(SeedFile(disk_id=1, relative_path="torrents/a.mkv", size_bytes=1, st_dev=1, inode=9,
                            last_scan_id=run0.id, last_seen_at=datetime.now(UTC)))
    db_session.add(
        TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q", username="u", password="p")
    )
    db_session.commit()

    class Client:
        def list_torrents(self, on_progress=None):
            return [ClientTorrentInfo(info_hash="h", name="a", save_path="", state="uploading",
                                      files=[ClientTorrentFileInfo(path_in_torrent="a.mkv", size_bytes=1)])]

    monkeypatch.setattr(adapter_factory, "build_torrent_client_adapter", lambda row: Client())
    monkeypatch.setattr(adapter_factory, "build_tracker_adapter", lambda row: CountingTracker())
    t2c_calls = []
    monkeypatch.setattr(matching, "run_torrent_to_client_matching", lambda *a, **k: t2c_calls.append(a))

    run = pipeline.start_run(db_session, "manual")
    pipeline.run_bulk_import(db_session, run, str(tmp_path))

    assert t2c_calls == []
    assert run.errors >= 1
    assert run.last_error.startswith("Torrent → client matching skipped: no file of the torrent clients")
