"""Prova end-to-end il caso riportato dall'utente: N episodi della stessa
serie, attraverso il resolver vero (FilenameParserResolver) e la pipeline
di risoluzione vera (resolve_unmatched_media_files) — non solo
CachingTMDBClient isolato (tests/test_tmdb_cache.py)."""


import httpx

from nazgarr import media_resolution, pipeline
from nazgarr.adapters.media_resolver.filename_parser import FilenameParserResolver
from nazgarr.models import Disk, MediaFile
from nazgarr.tmdb_cache import CachingTMDBClient
from nazgarr.tmdb_client import TMDBClient
from tests.fakes import make_media_file


def test_a_full_season_of_episodes_costs_one_tmdb_call(db_session, tmp_path):
    disk = Disk(label="disk1", root_path="/mnt/disk1", media_rel_path="tv")
    db_session.add(disk)
    db_session.commit()
    run = pipeline.start_run(db_session, run_type="manual")

    for episode in range(1, 25):  # una stagione intera, 24 episodi
        make_media_file(db_session, disk, f"tv/Game.of.Thrones.S03E{episode:02d}.mkv", run)

    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"results": [{"id": 1399, "poster_path": "/got.jpg"}]})

    http_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.themoviedb.org/3")
    tmdb_client = CachingTMDBClient(db_session, TMDBClient(api_key="key123", client=http_client))
    resolver = FilenameParserResolver(tmdb_client)

    counts = media_resolution.resolve_unmatched_media_files(db_session, resolver, str(tmp_path / "posters"))

    assert counts == {"resolved": 24, "unresolved": 0, "excluded": 0, "corrected": 0}
    assert calls["count"] == 1, "24 episodi della stessa serie devono costare una sola chiamata TMDB"
    assert db_session.query(MediaFile).filter(MediaFile.media_item_id.isnot(None)).count() == 24
