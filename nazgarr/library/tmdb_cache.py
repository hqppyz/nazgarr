"""Cache persistente delle ricerche TMDB (docs/schema.sql, tabella
tmdb_search_cache) — nazgarr/library/resolution.py chiama il resolver una volta
per media_file, quindi senza questa cache ogni episodio di una stessa
serie (stesso titolo/anno secondo guessit) genera la propria chiamata di
rete a TMDB, identica a quella degli altri episodi.

CachingTMDBClient espone la stessa interfaccia di TMDBClient
(search_movie/search_tv) e la sostituisce in FilenameParserResolver senza
che quest'ultimo debba saperlo — l'unico punto che decide se/come
inserire la cache è nazgarr/integrations/adapter_factory.py::build_media_resolver().

Un miss (TMDB non ha niente per quella ricerca) non entra nella tabella:
un titolo che TMDB non conosce oggi può comparire domani (docs/schema.sql).
Resta però in memoria per MISS_TTL, legato a quello che si è cercato
(tipo, titolo normalizzato, anno): prima ogni run rifaceva la stessa ricerca
per ogni episodio di una serie che TMDB non trova, a ogni run (audit
2026-10-18). Un file rinominato cerca un altro titolo, quindi un'altra
chiave, e si cerca subito; un riavvio dimentica tutti i miss."""

import threading
import time

from sqlalchemy.orm import Session

from nazgarr.core.db_utils import bulk_upsert
from nazgarr.core.models import TmdbSearchCache
from nazgarr.library.tmdb_client import TMDBSearchClient, year_of


# Quanto si ricorda che una ricerca non ha trovato niente: un giorno, così un
# titolo aggiunto a TMDB si trova al più tardi la scansione del giorno dopo.
MISS_TTL_SECONDS = 24 * 3600
# Quante ricerche fallite al massimo: oltre, si tolgono le scadute e poi le più vecchie.
MAX_MISSES = 20_000

_misses: dict[tuple, float] = {}  # chiave -> quando è scaduta (time.monotonic)
_misses_lock = threading.Lock()


def _remember_miss(key: tuple, now: float) -> None:
    with _misses_lock:
        if len(_misses) >= MAX_MISSES:
            for stale in [k for k, expires in _misses.items() if expires <= now]:
                del _misses[stale]
            while len(_misses) >= MAX_MISSES:
                del _misses[next(iter(_misses))]  # la più vecchia (ordine di inserimento)
        _misses[key] = now + MISS_TTL_SECONDS


def _known_miss(key: tuple, now: float) -> bool:
    with _misses_lock:
        expires = _misses.get(key)
        if expires is None:
            return False
        if expires <= now:
            del _misses[key]
            return False
        return True


def forget_misses() -> None:
    """Dimentica tutti i miss (i test; un'azione esplicita dell'utente)."""
    with _misses_lock:
        _misses.clear()


class CachingTMDBClient:
    def __init__(self, session: Session, client: TMDBSearchClient):
        self._session = session
        self._client = client
        # I miss sono del database che li ha visti (nei test un DB per test).
        bind = session.get_bind()
        self._namespace = str(getattr(bind, "url", id(bind)))

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

        miss_key = (self._namespace, content_type, normalized_query, normalized_year)
        now = time.monotonic()
        if _known_miss(miss_key, now):
            return None
        result = search_fn(query, year)
        if result is None:
            # Mai nella tabella (docs/schema.sql), solo in memoria per un po'.
            _remember_miss(miss_key, now)
            return None

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
