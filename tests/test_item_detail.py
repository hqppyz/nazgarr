"""Scheda di dettaglio della vista poster (nazgarr/library_detail.py, API)."""

import fnmatch
from datetime import UTC, datetime

from nazgarr import library_detail, matching, pipeline, settings_repo
from nazgarr.api.library import _fnmatch_literal
from nazgarr.models import (
    Candidate,
    ClientTorrent,
    ClientTorrentFile,
    Disk,
    MatchReview,
    MediaFile,
    MediaItem,
    RadarrInstance,
    SeedFile,
    TorrentClient,
    Tracker,
)


def _movie(db_session):
    disk = Disk(label="d", root_path="/data", media_rel_path="media", torrents_rel_path="torrents")
    tracker = Tracker(label="ITT", adapter_type="unit3d", base_url="https://itatorrents.xyz", api_token="x")
    radarr = RadarrInstance(label="r", base_url="http://radarr:7878/", api_key="k")
    db_session.add_all([disk, tracker, radarr])
    db_session.commit()
    item = MediaItem(content_type="movie", tmdb_id=157336, title="Interstellar", year=2014, imdb_id="tt0816692",
                     arr_kind="radarr", arr_instance_id=radarr.id, arr_slug="interstellar-157336",
                     tmdb_poster_path="/p.jpg")
    db_session.add(item)
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    path = "media/movies/Interstellar (2014)/Interstellar.2014.1080p.BluRay.x265.mkv"
    mf = MediaFile(disk_id=disk.id, relative_path=path, size_bytes=100, st_dev=1, inode=1,
                   media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC))
    db_session.add(mf)
    db_session.commit()
    return disk, tracker, item, mf, run


def test_detail_shows_hardlinks_with_the_torrent_client_and_tracker(db_session):
    disk, tracker, item, mf, run = _movie(db_session)
    sf = SeedFile(disk_id=disk.id, relative_path="torrents/Interstellar.2014.1080p/Interstellar.mkv", size_bytes=100,
                  st_dev=1, inode=1, media_file_id=mf.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC))
    client = TorrentClient(label="qbit private", adapter_type="qui", base_url="http://qui")
    db_session.add_all([sf, client])
    db_session.commit()
    ct = ClientTorrent(torrent_client_id=client.id, info_hash="h", name="Interstellar.2014.1080p",
                       save_path="/data/torrents", state="uploading",
                       tracker_url="https://itatorrents.xyz/announce/secret", last_polled_at=datetime.now(UTC))
    db_session.add(ct)
    db_session.commit()
    db_session.add(ClientTorrentFile(
        client_torrent_id=ct.id, path_in_torrent="Interstellar.2014.1080p/Interstellar.mkv",
        size_bytes=100, seed_file_id=sf.id, last_scan_id=run.id,
    ))
    db_session.commit()

    detail = library_detail.item_detail(db_session, "movie", 157336)

    assert (detail["title"], detail["year"], detail["imdb_id"]) == ("Interstellar", 2014, "tt0816692")
    assert detail["arr_url"] == "http://radarr:7878/movie/interstellar-157336"
    assert detail["quality"] == "1080p · Blu-ray · H.265"
    (f,) = detail["files"]
    assert f["state"] == "seeding"
    (link,) = f["hardlinks"]
    assert link["relative_path"] == "torrents/Interstellar.2014.1080p/Interstellar.mkv"
    assert link["torrents"] == [{"name": "Interstellar.2014.1080p", "client": "qbit private",
                                 "tracker": "itatorrents.xyz", "state": "uploading", "client_enabled": True}]


def test_detail_sums_up_seeding_per_tracker_configured_or_not(db_session):
    disk, tracker, item, mf, run = _movie(db_session)
    other = Tracker(label="Other", adapter_type="unit3d", base_url="https://other.example", api_token="x")
    sf = SeedFile(disk_id=disk.id, relative_path="torrents/public/Interstellar.mkv", size_bytes=100,
                  st_dev=1, inode=1, media_file_id=mf.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC))
    public = TorrentClient(label="qbit public", adapter_type="qbittorrent", base_url="http://q", enabled=False)
    db_session.add_all([other, sf, public])
    db_session.commit()
    ct = ClientTorrent(torrent_client_id=public.id, info_hash="p", name="Interstellar.PUBLIC", save_path="/t",
                       state="stalledUP", tracker_url="udp://tracker.torrent.eu.org:451/announce",
                       last_polled_at=datetime.now(UTC))
    db_session.add(ct)
    db_session.commit()
    db_session.add(ClientTorrentFile(client_torrent_id=ct.id, path_in_torrent="Interstellar.mkv", size_bytes=100,
                                     seed_file_id=sf.id, last_scan_id=run.id))
    db_session.commit()

    overview = library_detail.item_detail(db_session, "movie", 157336)["trackers"]

    # Il tracker configurato di _movie e "Other" compaiono anche a zero; il
    # pubblico, non configurato, per host, con il client disattivato.
    assert [(g["label"], g["configured"], g["seeding"], g["total"]) for g in overview] == [
        (tracker.label, True, 0, 1), ("Other", True, 0, 1), ("tracker.torrent.eu.org", False, 1, 1),
    ]
    (entry,) = overview[2]["entries"]
    assert (entry["seed_path"], entry["client"], entry["client_enabled"]) == (
        "torrents/public/Interstellar.mkv", "qbit public", False,
    )


def test_detail_explains_what_was_searched_and_found(db_session):
    _disk, tracker, item, mf, _run = _movie(db_session)

    class Tracker1:
        def search_by_tmdb(self, tmdb_id):
            from nazgarr.adapters.tracker.base import TorrentCandidate
            return [TorrentCandidate(torrent_id_remote="9", info_hash=None, name="Interstellar.2160p", size_bytes=999,
                                     file_list=["x.mkv"], mediainfo_unique_id=None)]

    matching.run_media_to_torrent_matching(db_session, tracker, Tracker1())
    detail = library_detail.item_detail(db_session, "movie", 157336)

    (search,) = detail["searches"]
    assert search["tracker"] == "ITT" and search["files_searched"] == 1
    assert search["next_search_at"] > search["last_searched_at"]
    (candidate,) = detail["candidates"]
    assert (candidate["name"], candidate["confidence"]) == ("Interstellar.2160p", 0.0)
    assert detail["files"][0]["state"] == "orphan_media"


def test_detail_lists_reviews_waiting_for_approval(db_session):
    _disk, tracker, item, mf, _run = _movie(db_session)
    c = Candidate(media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x", size_bytes=100,
                  source="catalog_search", direction="media_to_torrent", confidence=0.99)
    db_session.add(c)
    db_session.commit()
    db_session.add(MatchReview(candidate_id=c.id, media_file_id=mf.id, status="auto_approved"))
    db_session.commit()

    detail = library_detail.item_detail(db_session, "movie", 157336)

    assert [r.status for r in detail["reviews"]] == ["auto_approved"]
    assert detail["files"][0]["in_review"] is True


def test_exclusion_pattern_matches_exactly_that_file_even_with_brackets():
    path = "media/movies/Bronson (2008)/Bronson.(2008).BDRip.1080p.[TbZ].mkv"
    pattern = _fnmatch_literal(path)
    assert fnmatch.fnmatch(path.lower(), pattern.lower())
    assert not fnmatch.fnmatch("media/movies/Bronson (2008)/Bronson.(2008).BDRip.1080p.T.mkv", pattern)


def test_exclude_endpoint_appends_once(client):
    body = {"relative_path": "media/movies/A [x]/a.mkv"}
    assert client.post("/api/library/exclude", json=body).json()["pattern"] == "media/movies/A [[]x[]]/a.mkv"
    client.post("/api/library/exclude", json=body)
    value = client.get("/api/settings/exclusion_patterns").json()["value"]
    assert value.splitlines() == ["media/movies/A [[]x[]]/a.mkv"]


def test_excluding_a_folder_excludes_everything_inside(client):
    from nazgarr.exclusions import CompiledExclusions

    body = {"relative_path": "torrents/Old/", "is_dir": True}
    pattern = client.post("/api/library/exclude", json=body).json()["pattern"]

    assert pattern == "torrents/Old/*"
    excluded = CompiledExclusions(patterns=[pattern])
    assert excluded.is_excluded("torrents/Old/a.mkv") and excluded.is_excluded("torrents/Old/Sub/b.srt")
    assert not excluded.is_excluded("torrents/Older/a.mkv")


def test_search_now_forces_a_new_search_for_that_item_only(db_session, monkeypatch):
    from nazgarr import adapter_factory
    from nazgarr.api import library as library_api

    _disk, tracker, item, mf, run = _movie(db_session)
    run.finished_at = datetime.now(UTC)  # nessuna run in corso: "Cerca ora" è permesso
    other = MediaItem(content_type="movie", tmdb_id=1)
    db_session.add(other)
    db_session.commit()
    db_session.add(MediaFile(disk_id=mf.disk_id, relative_path="media/other.mkv", size_bytes=5, st_dev=1, inode=2,
                             media_item_id=other.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC)))
    db_session.commit()
    searched = []

    class Recording:
        def search_by_tmdb(self, tmdb_id):
            searched.append(tmdb_id)
            return []

    monkeypatch.setattr(adapter_factory, "build_tracker_adapter", lambda row: Recording())
    settings_repo.set_setting(db_session, "rematch_interval_days", "7")
    library_api.search_item_now("movie", 157336, db_session)
    result = library_api.search_item_now("movie", 157336, db_session)  # ignora l'intervallo

    assert searched == [157336, 157336]
    assert result.files_searched == 1
