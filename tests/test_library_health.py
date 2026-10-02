from datetime import UTC, datetime

from nazgarr import health, pipeline
from nazgarr.models import (
    Candidate,
    ClientTorrentFile,
    Disk,
    MatchReview,
    MediaFile,
    MediaItem,
    SeedFile,
    Tracker,
)


def _base(db_session):
    disk = Disk(label="d", root_path="/mnt/d", media_rel_path="movies")
    db_session.add(disk)
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    return disk, run


def _media_file(db_session, disk, run, *, relative_path, size_bytes=100, inode=1):
    mf = MediaFile(
        disk_id=disk.id, relative_path=relative_path, size_bytes=size_bytes,
        st_dev=1, inode=inode, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(mf)
    db_session.commit()
    return mf


def test_empty_library_is_100_percent_healthy(db_session):
    snapshot = health.compute_snapshot(db_session)

    assert snapshot["health_pct"] == 100.0
    assert snapshot["total_media_size"] == 0
    assert snapshot["orphan_torrent_count"] == 0
    assert snapshot["ignored_count"] == 0
    assert snapshot["pending_review"] == 0
    assert snapshot["failed"] == 0
    assert snapshot["unmatched"] == 0


def test_health_pct_is_size_weighted(db_session):
    disk, run = _base(db_session)
    seeding_mf = _media_file(db_session, disk, run, relative_path="movies/a.mkv", size_bytes=75, inode=1)
    _media_file(db_session, disk, run, relative_path="movies/b.mkv", size_bytes=25, inode=2)  # orphan_media

    sf = SeedFile(
        disk_id=disk.id, relative_path="torrents/a.mkv", size_bytes=75, st_dev=1, inode=3,
        media_file_id=seeding_mf.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(sf)
    db_session.commit()
    db_session.add(ClientTorrentFile(
        client_torrent_id=_client_torrent(db_session), path_in_torrent="a.mkv", size_bytes=75,
        seed_file_id=sf.id, last_scan_id=run.id,
    ))
    db_session.commit()

    snapshot = health.compute_snapshot(db_session)

    assert snapshot["total_media_size"] == 100
    assert snapshot["seeding_media_size"] == 75
    assert snapshot["health_pct"] == 75.0


def test_orphan_torrent_and_ignored_counted_from_seed_files(db_session):
    disk, run = _base(db_session)
    db_session.add(SeedFile(
        disk_id=disk.id, relative_path="torrents/untracked.mkv", size_bytes=10, st_dev=1, inode=1,
        last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    ))
    ignored_sf = SeedFile(
        disk_id=disk.id, relative_path="torrents/cross-seed.mkv", size_bytes=10, st_dev=1, inode=2,
        last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(ignored_sf)
    db_session.commit()
    db_session.add(ClientTorrentFile(
        client_torrent_id=_client_torrent(db_session), path_in_torrent="cross-seed.mkv", size_bytes=10,
        seed_file_id=ignored_sf.id, last_scan_id=run.id,
    ))
    db_session.commit()

    snapshot = health.compute_snapshot(db_session)

    assert snapshot["orphan_torrent_count"] == 1
    assert snapshot["ignored_count"] == 1


def test_pending_review_and_failed_and_unmatched_counted(db_session):
    disk, run = _base(db_session)
    _media_file(db_session, disk, run, relative_path="movies/unmatched.mkv")  # no media_item -> unmatched

    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    db_session.add(tracker)
    db_session.commit()
    item = MediaItem(content_type="movie", tmdb_id=1)
    db_session.add(item)
    db_session.commit()
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x", size_bytes=1,
        source="catalog_search", direction="media_to_torrent", confidence=0.5,
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.add(MatchReview(candidate_id=candidate.id, status="pending"))
    db_session.commit()

    snapshot = health.compute_snapshot(db_session)

    assert snapshot["unmatched"] == 1
    assert snapshot["pending_review"] == 1
    assert snapshot["failed"] == 0


def _client_torrent(db_session):
    from nazgarr.models import ClientTorrent, TorrentClient

    tc = TorrentClient(label="c", adapter_type="qbittorrent", base_url="https://c.example")
    db_session.add(tc)
    db_session.commit()
    ct = ClientTorrent(
        torrent_client_id=tc.id, info_hash="deadbeef", name="x", save_path="/x", state="uploading",
        last_polled_at=datetime.now(UTC),
    )
    db_session.add(ct)
    db_session.commit()
    return ct.id
