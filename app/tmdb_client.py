"""Client TMDB minimale (solo ricerca, sezione 6 di docs/SPEC.md).

Nessuna libreria wrapper esterna: due endpoint (search/movie, search/tv)
sono l'unica cosa che serve al resolver di default, più /tv/{id} per il
solo poster delle serie risolte via Sonarr. `client` iniettabile
per i test (stesso pattern di app/adapters/torrent_client/qbittorrent.py),
mai una connessione reale nei test.
"""

from typing import Protocol

import httpx

TMDB_API_BASE = "https://api.themoviedb.org/3"


def year_of(date: str | None) -> int | None:
    """"2014-11-05" -> 2014, None/"" -> None."""
    try:
        return int(date[:4]) if date else None
    except ValueError:
        return None


# Sorgenti accettate da /find: IMDB e TVDB. MAL non c'è, e resta un id
# passato al tracker così com'è (docs/SPEC.md §15).
FIND_SOURCES = {"imdb": "imdb_id", "tvdb": "tvdb_id"}


def normalize_result(result: dict, content_type: str) -> dict:
    """Un risultato TMDB nella forma dei candidati di un upload."""
    return {
        "tmdb_id": result["id"],
        "content_type": content_type,
        "title": result.get("title") or result.get("name"),
        "original_title": result.get("original_title") or result.get("original_name"),
        "year": year_of(result.get("release_date") or result.get("first_air_date")),
        "poster_path": result.get("poster_path"),
        "overview": result.get("overview") or None,
    }


class TMDBSearchClient(Protocol):
    """Interfaccia strutturale condivisa da TMDBClient e da
    app.tmdb_cache.CachingTMDBClient — FilenameParserResolver accetta
    l'una o l'altra senza saperlo (typing strutturale, nessuna eredità)."""

    def search_movie(self, query: str, year: int | None = None) -> dict | None: ...
    def search_tv(self, query: str, year: int | None = None) -> dict | None: ...


class TMDBClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self._client = client or httpx.Client(base_url=TMDB_API_BASE, timeout=10.0)

    def search_movie(self, query: str, year: int | None = None) -> dict | None:
        # primary_release_year e non year: "year" su TMDB vale per QUALUNQUE
        # data di uscita (riedizioni comprese), e con una saga dallo stesso
        # titolo base restituiva il film sbagliato (es. Mission: Impossible
        # del 1996 cercando quello del 2018, per una riedizione).
        return self._search("/search/movie", query, {"primary_release_year": year} if year else {}, year)

    def search_tv(self, query: str, year: int | None = None) -> dict | None:
        return self._search("/search/tv", query, {"first_air_date_year": year} if year else {}, year)

    def details(self, content_type: str, tmdb_id: int) -> dict:
        """{title, year, poster_path} di un contenuto già identificato: una
        chiamata di dettaglio, mai una ricerca. Usata per completare le
        voci rimaste senza titolo o poster (media_resolution)."""
        path = f"/{'tv' if content_type == 'tv' else 'movie'}/{tmdb_id}"
        response = self._client.get(path, params={"api_key": self.api_key})
        response.raise_for_status()
        body = response.json()
        return {
            "title": body.get("title") or body.get("name"),
            "year": year_of(body.get("release_date") or body.get("first_air_date")),
            "poster_path": body.get("poster_path"),
        }

    def tv_poster_path(self, tmdb_id: int) -> str | None:
        """Poster di una serie già identificata (ArrResolver: Sonarr non dà
        artwork TMDB) — una chiamata di dettaglio, non una ricerca."""
        response = self._client.get(f"/tv/{tmdb_id}", params={"api_key": self.api_key})
        response.raise_for_status()
        return response.json().get("poster_path")

    # --- Flusso di upload v2 (docs/SPEC.md §9): più candidati, id esterni, dettagli

    def search_many(self, content_type: str, query: str, year: int | None = None) -> list[dict]:
        """Tutti i risultati di una ricerca, non solo il primo: sono i
        candidati fra cui l'utente sceglie al primo punto di approvazione."""
        path = "/search/tv" if content_type == "tv" else "/search/movie"
        params = {"api_key": self.api_key, "query": query}
        if year:
            params["first_air_date_year" if content_type == "tv" else "primary_release_year"] = year
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return [normalize_result(r, content_type) for r in response.json().get("results", [])]

    def find(self, source: str, external_id: str) -> list[dict]:
        """Contenuti TMDB con quell'id IMDB o TVDB (source: "imdb" | "tvdb")."""
        response = self._client.get(
            f"/find/{external_id}", params={"api_key": self.api_key, "external_source": FIND_SOURCES[source]}
        )
        response.raise_for_status()
        body = response.json()
        return [normalize_result(r, "movie") for r in body.get("movie_results", [])] + [
            normalize_result(r, "tv") for r in body.get("tv_results", [])
        ]

    def full_details(self, content_type: str, tmdb_id: int) -> dict:
        """Quello che serve per riconoscere il contenuto giusto e per
        l'upload: trama, generi, durata, cast, id esterni e, per le serie,
        le stagioni con il numero di episodi attesi."""
        path = f"/{'tv' if content_type == 'tv' else 'movie'}/{tmdb_id}"
        response = self._client.get(
            path, params={"api_key": self.api_key, "append_to_response": "external_ids,credits"}
        )
        response.raise_for_status()
        body = response.json()
        external = body.get("external_ids") or {}
        return {
            **normalize_result(body, content_type),
            "genres": [g["name"] for g in body.get("genres", [])],
            "runtime": body.get("runtime") or next(iter(body.get("episode_run_time") or []), None),
            "imdb_id": body.get("imdb_id") or external.get("imdb_id"),
            "tvdb_id": external.get("tvdb_id"),
            "cast": [c["name"] for c in (body.get("credits") or {}).get("cast", [])[:6]],
            "original_language": body.get("original_language"),
            "seasons": [
                {
                    "season_number": season["season_number"],
                    "name": season.get("name"),
                    "episode_count": season.get("episode_count") or 0,
                    "air_date": season.get("air_date"),
                }
                for season in body.get("seasons", [])
            ],
        }

    def _search(self, path: str, query: str, extra_params: dict, year: int | None = None) -> dict | None:
        params = {"api_key": self.api_key, "query": query, **extra_params}
        response = self._client.get(path, params=params)
        response.raise_for_status()
        results = response.json().get("results", [])
        if not results:
            return None
        # Fra i risultati, quello uscito proprio nell'anno del nome del file,
        # se c'è; altrimenti il più rilevante secondo TMDB.
        if year:
            for result in results:
                if year_of(result.get("release_date") or result.get("first_air_date")) == year:
                    return result
        return results[0]

