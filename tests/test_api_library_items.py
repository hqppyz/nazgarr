from datetime import UTC, datetime

from nazgarr.models import Disk, MediaFile, MediaItem, RunLog


def _session(client):
    return client.app.state.session_factory()


def test_library_items_groups_files_under_media_item(client):
    session = _session(client)
    try:
        disk = Disk(label="d", root_path="/mnt/d")
        session.add(disk)
        session.commit()
        run = RunLog(run_type="manual", started_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        item = MediaItem(content_type="movie", tmdb_id=157336, tmdb_poster_path="/poster.jpg")
        session.add(item)
        session.commit()
        mf = MediaFile(
            disk_id=disk.id, relative_path="movies/Interstellar.mkv", size_bytes=1,
            st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        )
        session.add(mf)
        session.commit()
    finally:
        session.close()

    response = client.get("/api/library/items")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["tmdb_id"] == 157336
    assert items[0]["has_poster"] is True
    assert len(items[0]["files"]) == 1
    assert items[0]["files"][0]["state"] == "orphan_media"


def test_library_items_empty_when_no_data(client):
    response = client.get("/api/library/items")
    assert response.status_code == 200
    assert response.json() == []


def test_poster_not_cached_returns_404(client):
    response = client.get("/api/library/posters/movie/999999.jpg")
    assert response.status_code == 404


def test_media_files_marks_excluded_by_pattern(client):
    client.put("/api/settings/exclusion_patterns", json={"value": "*.nfo"})
    session = _session(client)
    try:
        disk = Disk(label="d", root_path="/mnt/d")
        session.add(disk)
        session.commit()
        run = RunLog(run_type="manual", started_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        mf = MediaFile(
            disk_id=disk.id, relative_path="movies/Movie.2024.nfo", size_bytes=1,
            st_dev=1, inode=1, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        )
        session.add(mf)
        session.commit()
    finally:
        session.close()

    response = client.get("/api/media-files")
    assert response.status_code == 200
    assert response.json()[0]["excluded"] is True


def test_duplicates_endpoint_returns_groups(client):
    session = _session(client)
    try:
        disk = Disk(label="d", root_path="/mnt/d")
        session.add(disk)
        session.commit()
        run = RunLog(run_type="manual", started_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        session.add(MediaFile(
            disk_id=disk.id, relative_path="movies/A.mkv", size_bytes=10,
            st_dev=1, inode=1, content_hash="abc", last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        ))
        session.add(MediaFile(
            disk_id=disk.id, relative_path="movies/B.mkv", size_bytes=10,
            st_dev=1, inode=2, content_hash="abc", last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        ))
        session.commit()
    finally:
        session.close()

    response = client.get("/api/library/duplicates")
    assert response.status_code == 200
    groups = response.json()
    assert len(groups) == 1
    assert {f["relative_path"] for f in groups[0]["files"]} == {"movies/A.mkv", "movies/B.mkv"}
