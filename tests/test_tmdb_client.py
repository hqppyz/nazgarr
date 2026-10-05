import httpx
import pytest

from nazgarr.library.tmdb_client import TMDBClient


def _client_with_handler(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.themoviedb.org/3")


def test_search_movie_returns_first_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/search/movie")
        assert request.url.params["query"] == "Interstellar"
        assert request.url.params["api_key"] == "key123"
        return httpx.Response(200, json={"results": [{"id": 157336, "poster_path": "/interstellar.jpg"}]})

    client = TMDBClient(api_key="key123", client=_client_with_handler(handler))
    result = client.search_movie("Interstellar")

    assert result == {"id": 157336, "poster_path": "/interstellar.jpg"}


def test_search_movie_filters_on_the_primary_release_year():
    # "year" su TMDB vale per qualunque uscita (riedizioni comprese): con una
    # saga dallo stesso titolo base restituiva il film sbagliato.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["primary_release_year"] == "2014"
        assert "year" not in request.url.params
        return httpx.Response(200, json={"results": []})

    client = TMDBClient(api_key="key123", client=_client_with_handler(handler))
    client.search_movie("Interstellar", year=2014)


def test_search_movie_returns_none_on_no_results():
    handler = lambda request: httpx.Response(200, json={"results": []})  # noqa: E731
    client = TMDBClient(api_key="key123", client=_client_with_handler(handler))

    assert client.search_movie("Nonexistent Movie 9999") is None


def test_search_tv_uses_first_air_date_year_param():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/search/tv")
        assert request.url.params["first_air_date_year"] == "2011"
        return httpx.Response(200, json={"results": [{"id": 1399, "poster_path": "/got.jpg"}]})

    client = TMDBClient(api_key="key123", client=_client_with_handler(handler))
    result = client.search_tv("Game of Thrones", year=2011)

    assert result["id"] == 1399


def test_raises_on_http_error():
    handler = lambda request: httpx.Response(401, json={"status_message": "Invalid API key"})  # noqa: E731
    client = TMDBClient(api_key="bad-key", client=_client_with_handler(handler))

    with pytest.raises(httpx.HTTPStatusError):
        client.search_movie("Anything")


def test_search_prefers_the_result_released_in_the_requested_year():
    handler = lambda request: httpx.Response(200, json={"results": [  # noqa: E731
        {"id": 954, "title": "Mission: Impossible", "release_date": "1996-05-22"},
        {"id": 353081, "title": "Mission: Impossible - Fallout", "release_date": "2018-07-13"},
    ]})
    client = TMDBClient(api_key="key123", client=_client_with_handler(handler))

    assert client.search_movie("Mission Impossible Fallout", year=2018)["id"] == 353081

