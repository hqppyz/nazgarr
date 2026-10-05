"""Titoli, anni e poster delle voci della libreria (vista poster): salvati
alla risoluzione, completati per le voci vecchie, un poster per contenuto
senza collisioni fra film e serie con lo stesso tmdb_id."""

import os

from nazgarr.adapters.media_resolver.base import ResolvedMedia
from nazgarr.core.models import MediaItem
from nazgarr.integrations.arr import ArrIdentity, ArrIndex
from nazgarr.library import poster_cache
from nazgarr.library import resolution as media_resolution


def test_resolution_stores_title_and_year(db_session):
    item = media_resolution.get_or_create_media_item(
        db_session, ResolvedMedia(tmdb_id=157336, content_type="movie", title="Interstellar", year=2014)
    )
    assert (item.title, item.year) == ("Interstellar", 2014)


def test_an_existing_item_without_title_is_completed_by_a_new_resolution(db_session):
    db_session.add(MediaItem(content_type="movie", tmdb_id=157336))
    db_session.commit()

    item = media_resolution.get_or_create_media_item(
        db_session, ResolvedMedia(tmdb_id=157336, content_type="movie", title="Interstellar", year=2014,
                                  poster_path="/p.jpg")
    )
    assert (item.title, item.year, item.tmdb_poster_path) == ("Interstellar", 2014, "/p.jpg")


def test_complete_media_items_prefers_arr_then_calls_tmdb_once_per_content(db_session, tmp_path, monkeypatch):
    downloads = []
    monkeypatch.setattr(media_resolution, "download_poster",
                        lambda d, ct, tid, pp: downloads.append((ct, tid, pp)))
    db_session.add_all([
        MediaItem(content_type="movie", tmdb_id=1),
        *[MediaItem(content_type="tv", tmdb_id=1399, season_number=1, episode_number=e) for e in (1, 2, 3)],
    ])
    db_session.commit()
    index = ArrIndex()
    index.add_identity("/m/a.mkv", 1, ArrIdentity(source="radarr", content_type="movie", tmdb_id=1,
                                                  title="From Radarr", year=2001, poster_path="/r.jpg"))
    calls = []

    def details(content_type, tmdb_id):
        calls.append((content_type, tmdb_id))
        return {"title": "Game of Thrones", "year": 2011, "poster_path": "/got.jpg"}

    counts = media_resolution.complete_media_items(db_session, str(tmp_path), index, details)

    assert counts == {"completed": 2, "failed": 0}
    assert calls == [("tv", 1399)]  # una sola chiamata per tre episodi, nessuna per il film
    titles = {(i.content_type, i.title, i.year) for i in db_session.query(MediaItem).all()}
    assert titles == {("movie", "From Radarr", 2001), ("tv", "Game of Thrones", 2011)}
    assert sorted(downloads) == [("movie", 1, "/r.jpg"), ("tv", 1399, "/got.jpg")]


def test_movie_and_series_with_the_same_tmdb_id_get_separate_poster_files(tmp_path):
    assert poster_cache.poster_file(str(tmp_path), "movie", 1399) != poster_cache.poster_file(str(tmp_path), "tv", 1399)
    assert os.path.basename(poster_cache.poster_file(str(tmp_path), "tv", 1399)) == "tv-1399.jpg"


def test_items_overview_flags_duplicates_and_files_in_review(db_session):
    from datetime import UTC, datetime

    from nazgarr.core.models import Candidate, Disk, MatchReview, MediaFile, Tracker
    from nazgarr.library import states as library
    from nazgarr.reseed import pipeline

    disk = Disk(label="d", root_path="/mnt/d", media_rel_path="media")
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    item = MediaItem(content_type="movie", tmdb_id=1, title="A", year=2000)
    db_session.add_all([disk, tracker, item])
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    copies = [
        MediaFile(disk_id=disk.id, relative_path=f"media/A{i}/a.mkv", size_bytes=10, st_dev=1, inode=i,
                  content_hash="same", media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC))
        for i in (1, 2)
    ]
    db_session.add_all(copies)
    db_session.commit()
    c = Candidate(media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x", size_bytes=10,
                  source="catalog_search", direction="media_to_torrent", confidence=0.5)
    db_session.add(c)
    db_session.commit()
    db_session.add(MatchReview(candidate_id=c.id, media_file_id=copies[0].id, status="pending"))
    db_session.commit()

    (overview,) = library.media_items_overview(db_session)

    flags = {f["relative_path"]: (f["duplicate"], f["in_review"]) for f in overview["files"]}
    assert flags == {"media/A1/a.mkv": (True, True), "media/A2/a.mkv": (True, False)}
    assert (overview["title"], overview["year"]) == ("A", 2000)


def test_tree_views_expose_the_content_of_each_file_for_the_detail_sheet(db_session):
    from datetime import UTC, datetime

    from nazgarr.core.models import Disk, MediaFile, SeedFile
    from nazgarr.library import states as library
    from nazgarr.reseed import pipeline

    disk = Disk(label="d", root_path="/mnt/d", media_rel_path="media", torrents_rel_path="torrents")
    item = MediaItem(content_type="tv", tmdb_id=1399, season_number=1, episode_number=1)
    db_session.add_all([disk, item])
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    video = MediaFile(disk_id=disk.id, relative_path="media/tv/S01E01.mkv", size_bytes=1, st_dev=1, inode=1,
                      media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC))
    nfo = MediaFile(disk_id=disk.id, relative_path="media/tv/S01E01.nfo", size_bytes=1, st_dev=1, inode=2,
                    last_scan_id=run.id, last_seen_at=datetime.now(UTC))
    db_session.add_all([video, nfo])
    db_session.commit()
    db_session.add(SeedFile(disk_id=disk.id, relative_path="torrents/S01E01.mkv", size_bytes=1, st_dev=1, inode=1,
                            media_file_id=video.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC)))
    db_session.commit()

    media = {f["relative_path"]: (f["content_type"], f["tmdb_id"]) for f in library.media_file_states(db_session)}
    assert media == {"media/tv/S01E01.mkv": ("tv", 1399), "media/tv/S01E01.nfo": (None, None)}
    (seed,) = library.seed_file_states(db_session)
    assert (seed["content_type"], seed["tmdb_id"]) == ("tv", 1399)
