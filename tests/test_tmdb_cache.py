"""CachingTMDBClient: risolve la richiesta dell'utente ("le chiamate TMDB
partono per ogni file anche se sono episodi della stessa serie") — un
titolo/anno già visto non deve generare una seconda chiamata di rete."""

from nazgarr.models import TmdbSearchCache
from nazgarr.tmdb_cache import CachingTMDBClient


class _CountingClient:
    def __init__(self, movie_result=None, tv_result=None):
        self.movie_result = movie_result
        self.tv_result = tv_result
        self.movie_calls = 0
        self.tv_calls = 0

    def search_movie(self, query, year=None):
        self.movie_calls += 1
        return self.movie_result

    def search_tv(self, query, year=None):
        self.tv_calls += 1
        return self.tv_result


def test_second_lookup_with_same_key_does_not_hit_the_underlying_client(db_session):
    inner = _CountingClient(tv_result={"id": 1399, "poster_path": "/got.jpg"})
    client = CachingTMDBClient(db_session, inner)

    first = client.search_tv("Game of Thrones", 2011)
    second = client.search_tv("Game of Thrones", 2011)

    assert first == {"id": 1399, "poster_path": "/got.jpg"}
    assert second == {"id": 1399, "poster_path": "/got.jpg", "title": None, "year": None}
    assert inner.tv_calls == 1
    assert db_session.query(TmdbSearchCache).count() == 1


def test_many_episodes_of_the_same_show_cost_one_network_call(db_session):
    inner = _CountingClient(tv_result={"id": 1399, "poster_path": "/got.jpg"})
    client = CachingTMDBClient(db_session, inner)

    for _ in range(24):  # una stagione intera
        result = client.search_tv("Game of Thrones", 2011)
        assert result["id"] == 1399

    assert inner.tv_calls == 1


def test_query_normalization_is_case_and_whitespace_insensitive(db_session):
    inner = _CountingClient(tv_result={"id": 1399, "poster_path": None})
    client = CachingTMDBClient(db_session, inner)

    client.search_tv("Game of Thrones", 2011)
    client.search_tv("  GAME OF THRONES  ", 2011)

    assert inner.tv_calls == 1


def test_no_year_and_year_zero_share_the_same_cache_bucket(db_session):
    inner = _CountingClient(movie_result={"id": 42, "poster_path": None})
    client = CachingTMDBClient(db_session, inner)

    client.search_movie("Unknown Year Movie", None)
    client.search_movie("Unknown Year Movie", 0)

    assert inner.movie_calls == 1


def test_different_years_are_different_cache_entries(db_session):
    inner = _CountingClient(movie_result={"id": 42, "poster_path": None})
    client = CachingTMDBClient(db_session, inner)

    client.search_movie("Dune", 1984)
    client.search_movie("Dune", 2021)

    assert inner.movie_calls == 2
    assert db_session.query(TmdbSearchCache).count() == 2


def test_movie_and_tv_with_the_same_title_are_different_cache_entries(db_session):
    inner = _CountingClient(movie_result={"id": 1, "poster_path": None}, tv_result={"id": 2, "poster_path": None})
    client = CachingTMDBClient(db_session, inner)

    movie = client.search_movie("Fargo", 1996)
    tv = client.search_tv("Fargo", 1996)

    assert movie["id"] == 1
    assert tv["id"] == 2
    assert inner.movie_calls == 1
    assert inner.tv_calls == 1


def test_a_miss_is_never_cached_and_is_retried_on_the_next_call(db_session):
    inner = _CountingClient(tv_result=None)
    client = CachingTMDBClient(db_session, inner)

    assert client.search_tv("Nonexistent Show", 2099) is None
    assert client.search_tv("Nonexistent Show", 2099) is None

    assert inner.tv_calls == 2
    assert db_session.query(TmdbSearchCache).count() == 0
