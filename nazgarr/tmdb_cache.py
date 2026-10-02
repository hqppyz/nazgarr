"""Cache persistente delle ricerche TMDB (docs/schema.sql, tabella
tmdb_search_cache) — nazgarr/media_resolution.py chiama il resolver una volta
per media_file, quindi senza questa cache ogni episodio di una stessa
serie (stesso titolo/anno secondo guessit) genera la propria chiamata di
rete a TMDB, identica a quella degli altri episodi.

CachingTMDBClient espone la stessa interfaccia di TMDBClient
(search_movie/search_tv) e la sostituisce in FilenameParserResolver senza
che quest'ultimo debba saperlo — l'unico punto che decide se/come
inserire la cache è nazgarr/adapter_factory.py::build_media_resolver()."""

from sqlalchemy.orm import Session

from nazgarr.db_utils import bulk_upsert
from nazgarr.models import TmdbSearchCache
from nazgarr.tmdb_client import TMDBSearchClient, year_of


class CachingTMDBClient:
    def __init__(self, session: Session, client: TMDBSearchClient):
        self._session = session
        self._client = client

    def search_movie(self, query: str, year: int | None = None) -> dict | None:
        return self._search("movie", self._client.search_movie, query, year)

    def search_tv(self, query: str, year: int | None = None) -> dict | None:
        return self._search("tv", self._client.search_tv, query, year)

    def _search(self, content_type: str, search_fn, query: str, year: int | None) -> dict | None:
        # "v2|": le ricerche salvate prima usavano un filtro sull'anno diverso
        # (year invece di primary_release_year) e potevano puntare al film
        # sbagliato di una saga: non vanno più riusate.
        normalized_query = f"v2|{query.strip().lower()}"
        normalized_year = year or 0

        cached = (
            self._session.query(TmdbSearchCache)
            .filter_by(content_type=content_type, query=normalized_query, year=normalized_year)
            .one_or_none()
        )
        if cached is not None:
            return {
                "id": cached.tmdb_id, "poster_path": cached.poster_path,
                "title": cached.result_title, "year": cached.result_year,
            }

        result = search_fn(query, year)
        if result is None:
            return None  # mai cachato un miss — vedi il motivo nel docstring di docs/schema.sql

        bulk_upsert(
            self._session, TmdbSearchCache.__table__,
            [{
                "content_type": content_type, "query": normalized_query, "year": normalized_year,
                "tmdb_id": result["id"], "poster_path": result.get("poster_path"),
                "result_title": result.get("title") or result.get("name"),
                "result_year": year_of(result.get("release_date") or result.get("first_air_date")),
            }],
            conflict_cols=["content_type", "query", "year"],
            update_cols=["tmdb_id", "poster_path", "result_title", "result_year"],
        )
        self._session.commit()
        return result
