"""Integrazione Radarr/Sonarr (nazgarr/arr.py, ArrResolver, match_from_history).
Payload modellati sulla forma reale delle API v3 (Radarr 6.3, Sonarr 4.0),
nessuna chiamata di rete."""

import hashlib
from datetime import UTC, datetime

import pytest

from nazgarr import adapter_factory, matching, pipeline, settings_repo
from nazgarr.adapters.media_resolver.arr import ArrResolver
from nazgarr.adapters.media_resolver.base import MediaResolverAdapter, ResolvedMedia
from nazgarr.arr import ArrGrab, ArrIdentity, ArrIndex, build_arr_index, path_key
from nazgarr.models import Candidate, Disk, MediaFile, MediaItem, RadarrInstance, SonarrInstance, Tracker

GUID = "https://itatorrents.xyz/torrent/download/4242.deadbeefpasskey"


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


def _single_file_torrent(content: bytes, name: str, piece_length: int = 16) -> bytes:
    pieces = b"".join(
        hashlib.sha1(content[i : i + piece_length]).digest() for i in range(0, len(content), piece_length)
    )
    return _bencode({"info": {"name": name, "piece length": piece_length, "pieces": pieces, "length": len(content)}})


class FakeApi:
    instance_id = None

    def __init__(self, responses: dict[str, object], history: dict[int, list[dict]] | None = None):
        self._responses = responses
        self._history = history or {}

    def get(self, path, **params):
        key = f"{path}?seriesId={params['seriesId']}" if "seriesId" in params else path
        value = self._responses[key]
        if isinstance(value, Exception):
            raise value
        return value

    def history(self, event_type):
        yield from self._history.get(event_type, [])


def _radarr_api():
    return FakeApi(
        {
            "/api/v3/movie": [
                {
                    "tmdbId": 157336, "hasFile": True,
                    "images": [{"coverType": "poster", "remoteUrl": "https://image.tmdb.org/t/p/original/abc.jpg"}],
                    "movieFile": {"path": "/data/media/movies/Interstellar (2014)/Interstellar.mkv", "size": 64,
                                  "sceneName": "Interstellar.2014.1080p.BluRay.x264-GRP"},
                },
                {"tmdbId": 1, "hasFile": False, "movieFile": None},
            ]
        },
        {
            1: [
                {"downloadId": "HASH1", "data": {"guid": GUID, "torrentInfoHash": "HASH1", "indexer": "ITT"}},
                {"downloadId": "HASH2", "data": {"guid": "https://other.example/details?id=9"}},
            ],
            3: [
                {
                    "downloadId": "HASH1",
                    "data": {
                        "size": "64",
                        "importedPath": "/data/media/movies/Interstellar (2014)/Interstellar.mkv",
                        "droppedPath": "/data/torrents/movies/Interstellar.2014.Release/Interstellar.mkv",
                    },
                },
                {"downloadId": "HASH2", "data": {"size": "10", "importedPath": "/data/media/movies/X/x.mkv"}},
            ],
        },
    )


def _sonarr_api():
    return FakeApi(
        {
            "/api/v3/series": [{"id": 7, "tmdbId": 1399}, {"id": 8, "tmdbId": None}],
            "/api/v3/episode?seriesId=7": [
                {"seasonNumber": 1, "episodeNumber": 2, "episodeFileId": 70},
                {"seasonNumber": 1, "episodeNumber": 3, "episodeFileId": 70},
            ],
            "/api/v3/episodefile?seriesId=7": [
                {"id": 70, "path": "/data/media/tv/Show/Season 01/Show.S01E02E03.mkv", "size": 500},
            ],
        }
    )


def _instances(db_session):
    radarr = RadarrInstance(label="radarr", base_url="http://radarr", api_key="k")
    sonarr = SonarrInstance(label="sonarr", base_url="http://sonarr", api_key="k", priority=5)
    db_session.add_all([radarr, sonarr])
    db_session.commit()
    return radarr, sonarr


def test_index_maps_identities_and_history_grabs(db_session):
    _instances(db_session)
    apis = {"radarr": _radarr_api(), "sonarr": _sonarr_api()}
    index = build_arr_index(db_session, api_factory=lambda inst: apis[inst.label])

    movie = index.identity_for("/mnt/disk1/Movies/Interstellar (2014)/Interstellar.mkv", 64)
    assert movie == ArrIdentity(source="radarr", content_type="movie", tmdb_id=157336, poster_path="/abc.jpg",
                                scene_name="Interstellar.2014.1080p.BluRay.x264-GRP")
    episode = index.identity_for("/mnt/disk1/TV/Season 01/show.s01e02e03.mkv", 500)
    assert episode == ArrIdentity(source="sonarr", content_type="tv", tmdb_id=1399, season_number=1, episode_number=2)

    # Stesso file sia dal lato libreria sia dal lato torrent.
    for path in ("/mnt/d/movies/Interstellar (2014)/Interstellar.mkv",
                 "/mnt/d/torrents/Interstellar.2014.Release/Interstellar.mkv"):
        grab = index.grab_for(path, 64)
        assert grab == ArrGrab(
            tracker_host="itatorrents.xyz", torrent_id_remote="4242", download_url=GUID,
            info_hash="hash1", indexer="ITT",
        )
    # guid non riconducibile a un id UNIT3D: nessun grab.
    assert index.grab_for("/any/X/x.mkv", 10) is None


def test_size_must_match_as_well_as_the_path_tail(db_session):
    _instances(db_session)
    apis = {"radarr": _radarr_api(), "sonarr": _sonarr_api()}
    index = build_arr_index(db_session, api_factory=lambda inst: apis[inst.label])

    assert index.identity_for("/mnt/d/Interstellar (2014)/Interstellar.mkv", 65) is None
    assert index.identity_for("/mnt/d/Other Folder/Interstellar.mkv", 64) is None


def test_unreachable_instance_is_skipped_not_fatal(db_session):
    import httpx

    _instances(db_session)
    apis = {"radarr": FakeApi({"/api/v3/movie": httpx.ConnectError("down")}), "sonarr": _sonarr_api()}
    index = build_arr_index(db_session, api_factory=lambda inst: apis[inst.label])

    assert index.counts == {"identities": 1, "grabs": 0, "imports": 0}


def test_path_key_uses_folder_and_filename_case_insensitively():
    assert path_key("/data/media/Movies/A (2020)/A.MKV") == "a (2020)/a.mkv"
    assert path_key("C:\\x\\A (2020)\\A.mkv") == "a (2020)/a.mkv"


class RecordingFallback(MediaResolverAdapter):
    SOURCE = "filename_parser"

    def __init__(self):
        self.calls = []

    def resolve(self, file_path):
        self.calls.append(file_path)
        return ResolvedMedia(tmdb_id=1, content_type="movie", source=self.SOURCE)


def test_arr_resolver_uses_index_then_falls_back(tmp_path):
    known = tmp_path / "Interstellar (2014)" / "Interstellar.mkv"
    known.parent.mkdir()
    known.write_bytes(b"x" * 64)
    unknown = tmp_path / "Other" / "other.mkv"
    unknown.parent.mkdir()
    unknown.write_bytes(b"x" * 10)
    index = ArrIndex()
    index.add_identity("/data/media/Interstellar (2014)/Interstellar.mkv", 64,
                       ArrIdentity(source="radarr", content_type="movie", tmdb_id=157336, poster_path="/abc.jpg"))
    fallback = RecordingFallback()
    resolver = ArrResolver(index, fallback=fallback)

    resolved = resolver.resolve(str(known))
    assert (resolved.tmdb_id, resolved.source, resolved.poster_path) == (157336, "radarr", "/abc.jpg")
    assert fallback.calls == []

    assert resolver.resolve(str(unknown)).source == "filename_parser"
    assert fallback.calls == [str(unknown)]


def test_arr_resolver_looks_up_a_tv_poster_once_per_series(tmp_path):
    index = ArrIndex()
    for ep in (1, 2):
        path = tmp_path / "Season 01" / f"e{ep}.mkv"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"x" * ep)
        index.add_identity(f"/tv/Season 01/e{ep}.mkv", ep, ArrIdentity(
            source="sonarr", content_type="tv", tmdb_id=1399, season_number=1, episode_number=ep,
        ))
    lookups = []
    resolver = ArrResolver(index, tv_poster_lookup=lambda tmdb_id: lookups.append(tmdb_id) or "/got.jpg")

    posters = [resolver.resolve(str(tmp_path / "Season 01" / f"e{ep}.mkv")).poster_path for ep in (1, 2)]

    assert posters == ["/got.jpg", "/got.jpg"]
    assert lookups == [1399]


def test_resolver_factory_works_without_tmdb_key_when_arr_knows_files(db_session):
    index = ArrIndex()
    index.add_identity("/a/b.mkv", 1, ArrIdentity(source="radarr", content_type="movie", tmdb_id=1))

    assert isinstance(adapter_factory.build_media_resolver(db_session, index), ArrResolver)
    with pytest.raises(adapter_factory.TmdbApiKeyMissingError):
        adapter_factory.build_media_resolver(db_session, ArrIndex())


class HistoryTracker:
    def __init__(self, torrent: bytes | None = None, search_results=None):
        self.torrent = torrent
        self.search_calls = 0
        self.downloads = []
        self._search_results = search_results or []

    def search_by_tmdb(self, tmdb_id):
        self.search_calls += 1
        return self._search_results

    def download_torrent(self, url):
        self.downloads.append(url)
        return self.torrent


def _orphan(db_session, tmp_path, content: bytes):
    folder = tmp_path / "movies" / "Interstellar (2014)"
    folder.mkdir(parents=True)
    (folder / "Interstellar.mkv").write_bytes(content)
    tracker = Tracker(label="itt", adapter_type="unit3d", base_url="https://itatorrents.xyz", api_token="x")
    disk = Disk(label="d", root_path=str(tmp_path), media_rel_path="movies")
    db_session.add_all([tracker, disk])
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    item = MediaItem(content_type="movie", tmdb_id=157336)
    db_session.add(item)
    db_session.commit()
    mf = MediaFile(
        disk_id=disk.id, relative_path="movies/Interstellar (2014)/Interstellar.mkv", size_bytes=len(content),
        st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(mf)
    db_session.commit()
    index = ArrIndex()
    index.add_grab("/data/media/movies/Interstellar (2014)/Interstellar.mkv", len(content), ArrGrab(
        tracker_host="itatorrents.xyz", torrent_id_remote="4242", download_url=GUID, info_hash="h", indexer="ITT",
    ))
    return tracker, index


def test_history_grab_replaces_the_catalog_search(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    content = b"0123456789abcdef" * 4
    tracker, index = _orphan(db_session, tmp_path, content)
    adapter = HistoryTracker(torrent=_single_file_torrent(content, "Interstellar.mkv"))

    totals = matching.run_media_to_torrent_matching(db_session, tracker, adapter, index)

    assert totals["from_history"] == 1
    assert adapter.search_calls == 0
    assert adapter.downloads == [GUID]
    candidate = db_session.query(Candidate).one()
    assert (candidate.source, candidate.torrent_id_remote, candidate.download_link) == ("history", "4242", GUID)
    assert candidate.piece_verified is True
    assert candidate.confidence == matching.CONFIDENCE_PIECE_VERIFIED


def test_history_torrent_that_does_not_match_falls_back_to_the_search(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    content = b"0123456789abcdef" * 4
    tracker, index = _orphan(db_session, tmp_path, content)
    adapter = HistoryTracker(torrent=_single_file_torrent(b"z" * 64, "Interstellar.mkv"))

    totals = matching.run_media_to_torrent_matching(db_session, tracker, adapter, index)

    assert totals["from_history"] == 0
    assert adapter.search_calls == 1
    # Il candidato dalla history resta nell'audit trail, a confidence 0.
    assert db_session.query(Candidate).filter_by(source="history").one().ambiguity_reason == "piece_mismatch"


def test_history_grab_for_another_tracker_is_ignored(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    content = b"0123456789abcdef" * 4
    tracker, index = _orphan(db_session, tmp_path, content)
    tracker.base_url = "https://another-tracker.example"
    db_session.commit()
    adapter = HistoryTracker(torrent=_single_file_torrent(content, "Interstellar.mkv"))

    matching.run_media_to_torrent_matching(db_session, tracker, adapter, index)

    assert adapter.downloads == []
    assert adapter.search_calls == 1


def test_pipeline_resolves_through_arr_without_tmdb(db_session, tmp_path, monkeypatch):
    from nazgarr import arr as arr_module

    folder = tmp_path / "movies" / "Interstellar (2014)"
    folder.mkdir(parents=True)
    (folder / "Interstellar.mkv").write_bytes(b"x" * 64)
    db_session.add(Disk(label="d", root_path=str(tmp_path), media_rel_path="movies"))
    db_session.commit()
    index = ArrIndex()
    index.add_identity("/data/media/Interstellar (2014)/Interstellar.mkv", 64,
                       ArrIdentity(source="radarr", content_type="movie", tmdb_id=157336))
    monkeypatch.setattr(arr_module, "build_arr_index", lambda session: index)
    settings_repo.set_setting(db_session, "tmdb_api_key", "")

    run = pipeline.start_run(db_session, "manual")
    pipeline.run_bulk_import(db_session, run, str(tmp_path / "data"))

    mf = db_session.query(MediaFile).one()
    assert mf.resolver_source == "radarr"
    assert mf.media_item.tmdb_id == 157336


def test_stale_history_link_falls_back_to_the_current_download_link(db_session, tmp_path, monkeypatch):
    """Il guid della history ha la chiave di quando è stato fatto il grab: se
    il tracker lo rifiuta si usa il download_link attuale del torrent, ed è
    quello che finisce nel candidato (lo scaricherà il client)."""
    from nazgarr.adapters.tracker.base import TorrentCandidate, UploadError

    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    content = b"0123456789abcdef" * 4
    tracker, index = _orphan(db_session, tmp_path, content)
    fresh = "https://itatorrents.xyz/torrent/download/4242.currentkey"

    class StaleKeyTracker(HistoryTracker):
        detail_calls = 0

        def download_torrent(self, url):
            self.downloads.append(url)
            if url == GUID:
                raise UploadError("The tracker rejected the link (redirect to login)")
            return self.torrent

        def get_torrent_detail(self, torrent_id_remote):
            StaleKeyTracker.detail_calls += 1
            return TorrentCandidate(torrent_id_remote=torrent_id_remote, info_hash=None, name="x", size_bytes=64,
                                    file_list=None, mediainfo_unique_id=None, download_link=fresh)

    adapter = StaleKeyTracker(torrent=_single_file_torrent(content, "Interstellar.mkv"))
    totals = matching.run_media_to_torrent_matching(db_session, tracker, adapter, index)

    assert totals["from_history"] == 1
    assert adapter.search_calls == 0
    assert adapter.downloads == [GUID, fresh]
    assert StaleKeyTracker.detail_calls == 1
    assert db_session.query(Candidate).one().download_link == fresh


def test_history_link_is_rewritten_with_the_current_key_without_extra_calls(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(matching, "compute_unique_id", lambda path: None)
    content = b"0123456789abcdef" * 4
    tracker, index = _orphan(db_session, tmp_path, content)
    current = "https://itatorrents.xyz/torrent/download/4242.currentkey"

    class KeyedTracker(HistoryTracker):
        def rewrite_download_link(self, url):
            return url.replace("deadbeefpasskey", "currentkey")

        def get_torrent_detail(self, torrent_id_remote):
            raise AssertionError("con la chiave attuale nota non serve il dettaglio")

    adapter = KeyedTracker(torrent=_single_file_torrent(content, "Interstellar.mkv"))
    matching.run_media_to_torrent_matching(db_session, tracker, adapter, index)

    assert adapter.downloads == [current]
    assert db_session.query(Candidate).one().download_link == current


def test_pipeline_remembers_the_learned_key_and_the_api_never_returns_it(db_session, tmp_path, monkeypatch):
    from nazgarr import adapter_factory
    from nazgarr.api.trackers import TrackerResponse

    tracker = Tracker(label="itt", adapter_type="unit3d", base_url="https://itatorrents.xyz", api_token="x")
    db_session.add(tracker)
    db_session.commit()

    class Learning:
        rss_key = "learnedkey"

        def search_by_tmdb(self, tmdb_id):
            return []

    monkeypatch.setattr(adapter_factory, "build_tracker_adapter", lambda row: Learning())
    run = pipeline.start_run(db_session, "manual")
    pipeline.run_bulk_import(db_session, run, str(tmp_path / "data"))

    db_session.refresh(tracker)
    assert tracker.rss_key == "learnedkey"
    body = TrackerResponse.from_model(tracker).model_dump()
    assert body["has_rss_key"] is True
    assert "learnedkey" not in str(body)


def test_history_pages_are_fetched_in_parallel_and_yielded_in_order():
    import httpx

    from nazgarr.arr import HISTORY_PAGE_SIZE, ArrApi

    total = HISTORY_PAGE_SIZE * 2 + 5

    def handler(request):
        page = int(request.url.params["page"])
        start = (page - 1) * HISTORY_PAGE_SIZE
        records = [{"id": i} for i in range(start, min(start + HISTORY_PAGE_SIZE, total))]
        return httpx.Response(200, json={"records": records, "totalRecords": total})

    instance = RadarrInstance(id=1, label="r", base_url="http://radarr", api_key="k")
    api = ArrApi(instance, client=httpx.Client(transport=httpx.MockTransport(handler), base_url="http://radarr"))

    ids = [event["id"] for event in api.history(1)]

    assert ids == list(range(total))
