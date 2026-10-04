import httpx

from nazgarr.adapters.media_resolver.filename_parser import FilenameParserResolver
from nazgarr.library.tmdb_client import TMDBClient


def _resolver(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.themoviedb.org/3")
    return FilenameParserResolver(TMDBClient(api_key="key123", client=client))


def test_resolves_a_movie():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/search/movie")
        assert "Interstellar" in request.url.params["query"]
        return httpx.Response(200, json={"results": [{"id": 157336, "poster_path": "/interstellar.jpg"}]})

    resolver = _resolver(handler)
    result = resolver.resolve("Interstellar.2014.2160p.UHD.BluRay.mkv")

    assert result is not None
    assert result.tmdb_id == 157336
    assert result.content_type == "movie"
    assert result.season_number is None
    assert result.poster_path == "/interstellar.jpg"


def test_resolves_a_tv_episode():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/search/tv")
        return httpx.Response(200, json={"results": [{"id": 1399, "poster_path": "/got.jpg"}]})

    resolver = _resolver(handler)
    result = resolver.resolve("Game.of.Thrones.S03E09.The.Rains.of.Castamere.mkv")

    assert result is not None
    assert result.tmdb_id == 1399
    assert result.content_type == "tv"
    assert result.season_number == 3
    assert result.episode_number == 9


def test_returns_none_when_tmdb_has_no_match():
    handler = lambda request: httpx.Response(200, json={"results": []})  # noqa: E731
    resolver = _resolver(handler)

    assert resolver.resolve("Interstellar.2014.mkv") is None


def test_returns_none_for_unparsable_filename():
    # guessit potrebbe comunque estrarre un titolo spurio da una stringa senza
    # senso — non assumiamo che TMDB non venga proprio chiamato, solo che il
    # risultato finale sia None quando TMDB non trova nulla di sensato.
    handler = lambda request: httpx.Response(200, json={"results": []})  # noqa: E731
    resolver = _resolver(handler)

    assert resolver.resolve("asdf1234.mkv") is None


def test_returns_none_for_tv_file_without_episode_number():
    # Un file senza season/episode isolabili (season pack) non è ancora gestito
    # qui — territorio del motore di matching, Fase 4 (docs/SPEC.md sezione 3).
    handler = lambda request: httpx.Response(200, json={"results": []})  # noqa: E731
    resolver = _resolver(handler)

    assert resolver.resolve("Game.of.Thrones.Season.3.Complete.mkv") is None


def test_subtitle_is_part_of_the_search_so_a_saga_is_not_collapsed_into_one_film():
    from nazgarr.adapters.media_resolver.filename_parser import FilenameParserResolver

    searched = []

    class Tmdb:
        def search_movie(self, query, year=None):
            searched.append((query, year))
            return {"id": 353081, "title": "Mission: Impossible - Fallout", "release_date": "2018-07-13"}

        def search_tv(self, query, year=None):
            return None

    resolved = FilenameParserResolver(Tmdb()).resolve(
        "/data/media/movies/Mission Impossible - Fallout (2018)/Mission Impossible - Fallout (2018) Bluray-2160p.mkv"
    )

    assert searched[0] == ("Mission Impossible Fallout", 2018)
    assert (resolved.tmdb_id, resolved.title, resolved.year) == (353081, "Mission: Impossible - Fallout", 2018)


def test_falls_back_to_the_base_title_when_title_plus_subtitle_finds_nothing():
    from nazgarr.adapters.media_resolver.filename_parser import FilenameParserResolver

    searched = []

    class Tmdb:
        def search_movie(self, query, year=None):
            searched.append(query)
            return None if query == "Movie Directors Cut" else {"id": 1, "title": "Movie", "release_date": "2001-01-01"}

        def search_tv(self, query, year=None):
            return None

    FilenameParserResolver(Tmdb()).resolve("/m/Movie - Directors Cut (2001)/Movie - Directors Cut (2001).mkv")
    assert searched[-1] == "Movie"
