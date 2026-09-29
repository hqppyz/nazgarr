import pytest

from app import upload_identify
from app.adapters.media_resolver.base import ResolvedMedia
from app.upload_jobs import UploadJobError
from app.upload_source import scan_source
from tests.upload_helpers import FakeTMDB, tmdb_result, write_video


@pytest.mark.parametrize(("value", "expected"), [
    ("603", ("movie", 603)),
    ("tv/1399", ("tv", 1399)),
    ("movie:603", ("movie", 603)),
    ("https://www.themoviedb.org/tv/1399-game-of-thrones", ("tv", 1399)),
    ("https://themoviedb.org/movie/603-the-matrix?language=it", ("movie", 603)),
    ("abc", None),
])
def test_parse_tmdb_ref(value, expected):
    assert upload_identify.parse_tmdb_ref(value, "movie") == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("tt0133093", "tt0133093"), ("0133093", "tt0133093"),
    ("https://www.imdb.com/title/tt0133093/", "tt0133093"), ("x", None),
])
def test_normalize_imdb(value, expected):
    assert upload_identify.normalize_imdb(value) == expected


@pytest.fixture
def no_resolver(monkeypatch):
    class _Resolver:
        SOURCE = "filename_parser"
        resolved = None

        def resolve(self, file_path):
            return self.resolved

    resolver = _Resolver()
    monkeypatch.setattr(
        upload_identify.adapter_factory, "build_media_resolver", lambda session, arr_index=None: resolver
    )
    return resolver


def _with_tmdb(monkeypatch, fake):
    monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)


def test_resolver_first_then_search_prefers_the_year_and_dedupes(db_session, tmp_path, monkeypatch, no_resolver):
    layout = scan_source(str(write_video(tmp_path / "The.Matrix.1999.1080p.mkv")))
    no_resolver.resolved = ResolvedMedia(tmdb_id=603, content_type="movie", title="The Matrix", year=1999)
    fake = FakeTMDB(search={("movie", "The Matrix", 1999): [
        tmdb_result(9999, "The Matrix Revisited", 2001), tmdb_result(603, "The Matrix", 1999),
        tmdb_result(604, "The Matrix Reloaded", 1999), tmdb_result(605, "Other", 1999),
    ]})
    _with_tmdb(monkeypatch, fake)

    candidates = upload_identify.find_candidates(db_session, {}, layout)

    assert [c["tmdb_id"] for c in candidates] == [603, 604, 605, 9999]
    assert [c["source"] for c in candidates] == ["filename_parser", "search", "search", "search"]
    assert ("search", "tv", "The Matrix", 1999) not in fake.calls  # abbastanza risultati nel tipo rilevato


def test_few_results_also_search_the_other_type_and_retry_without_year(db_session, tmp_path, monkeypatch, no_resolver):
    layout = scan_source(str(write_video(tmp_path / "Chernobyl.2019.1080p.mkv")))
    fake = FakeTMDB(search={
        ("movie", "Chernobyl", None): [tmdb_result(1, "Chernobyl Diaries", 2012)],
        ("tv", "Chernobyl", 2019): [tmdb_result(87108, "Chernobyl", 2019, "tv")],
    })
    _with_tmdb(monkeypatch, fake)

    candidates = upload_identify.find_candidates(db_session, {}, layout)

    assert [(c["content_type"], c["tmdb_id"]) for c in candidates] == [("movie", 1), ("tv", 87108)]


def test_forced_ids_are_the_only_candidates(db_session, tmp_path, monkeypatch, no_resolver):
    layout = scan_source(str(write_video(tmp_path / "Show.S01E01.mkv")))
    no_resolver.resolved = ResolvedMedia(tmdb_id=1, content_type="tv")
    fake = FakeTMDB(
        details={("tv", 1399): {**tmdb_result(1399, "GoT", 2011, "tv"), "seasons": []}},
        find={("imdb", "tt0944947"): [tmdb_result(1399, "GoT", 2011, "tv")],
              ("tvdb", "121361"): [tmdb_result(1399, "GoT", 2011, "tv")]},
    )
    _with_tmdb(monkeypatch, fake)

    candidates = upload_identify.find_candidates(
        db_session, {"tmdb": "1399", "imdb": "0944947", "tvdb": 121361}, layout
    )

    assert [(c["tmdb_id"], c["source"]) for c in candidates] == [(1399, "forced_tmdb")]
    assert ("find", "imdb", "tt0944947") in fake.calls


def test_invalid_forced_tmdb_id_is_a_coded_error(db_session, tmp_path, monkeypatch, no_resolver):
    layout = scan_source(str(write_video(tmp_path / "Movie.2024.mkv")))
    _with_tmdb(monkeypatch, FakeTMDB())

    with pytest.raises(UploadJobError) as exc:
        upload_identify.find_candidates(db_session, {"tmdb": "nope"}, layout)
    assert exc.value.code == "upload_invalid_tmdb_id"


def test_without_tmdb_key_only_the_resolver_is_used(db_session, tmp_path, no_resolver):
    layout = scan_source(str(write_video(tmp_path / "Movie.2024.mkv")))
    no_resolver.resolved = ResolvedMedia(tmdb_id=7, content_type="movie", source="radarr")

    candidates = upload_identify.find_candidates(db_session, {"tmdb": "603"}, layout)

    assert [(c["tmdb_id"], c["source"]) for c in candidates] == [(7, "radarr")]
