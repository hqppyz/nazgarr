"""Resolver Radarr/Sonarr (docs/SPEC.md §6): identità presa da ciò che
Radarr/Sonarr sanno già di un file (nazgarr/arr.py::ArrIndex), senza guessit né
una ricerca TMDB per titolo. Un file che non conoscono passa al resolver di
default (`fallback`), mai un "non risolto" solo perché l'integrazione
c'è."""

import os
from collections.abc import Callable

from nazgarr.adapters.media_resolver.base import MediaResolverAdapter, ResolvedMedia
from nazgarr.arr import ArrIndex


class ArrResolver(MediaResolverAdapter):
    SOURCE = "arr"

    def __init__(
        self,
        index: ArrIndex,
        fallback: MediaResolverAdapter | None = None,
        tv_poster_lookup: Callable[[int], str | None] | None = None,
    ):
        self._index = index
        self._fallback = fallback
        # Sonarr espone solo artwork TVDB: il poster TMDB di una serie costa
        # una chiamata di dettaglio, una sola volta per serie (memo qui) —
        # mai la ricerca per titolo di ogni episodio.
        self._tv_poster_lookup = tv_poster_lookup
        self._tv_posters: dict[int, str | None] = {}

    def resolve(self, file_path: str) -> ResolvedMedia | None:
        try:
            size = os.stat(file_path).st_size
        except OSError:
            size = None
        identity = self._index.identity_for(file_path, size) if size is not None else None
        if identity is None:
            return self._fallback.resolve(file_path) if self._fallback else None

        poster_path = identity.poster_path
        if poster_path is None and identity.content_type == "tv" and self._tv_poster_lookup:
            if identity.tmdb_id not in self._tv_posters:
                try:
                    self._tv_posters[identity.tmdb_id] = self._tv_poster_lookup(identity.tmdb_id)
                except Exception:
                    # Solo il poster: l'identità resta valida, placeholder in UI.
                    self._tv_posters[identity.tmdb_id] = None
            poster_path = self._tv_posters[identity.tmdb_id]

        return ResolvedMedia(
            tmdb_id=identity.tmdb_id,
            content_type=identity.content_type,
            season_number=identity.season_number,
            episode_number=identity.episode_number,
            poster_path=poster_path,
            source=identity.source,
            title=identity.title,
            year=identity.year,
            imdb_id=identity.imdb_id,
            arr_instance_id=identity.instance_id,
            arr_slug=identity.slug,
        )
