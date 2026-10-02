"""Contratto per gli adapter di risoluzione media (docs/SPEC.md sezione 6).

Vedi ratio-guardian per il precedente diretto: default = filename parser
(guessit) + lookup TMDB, mai una dipendenza da Sonarr/Radarr (adapter
opzionale, nazgarr/adapters/media_resolver/arr.py).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ResolvedMedia:
    tmdb_id: int
    content_type: str  # "movie" | "tv"
    season_number: int | None = None
    episode_number: int | None = None
    poster_path: str | None = None  # path relativo TMDB (es. "/abc123.jpg"), non un URL completo
    # Chi ha davvero risolto il file, se diverso dal SOURCE del resolver
    # (ArrResolver: "radarr"/"sonarr", o il resolver di ripiego).
    source: str | None = None
    title: str | None = None  # titolo del film / nome della serie, per la vista poster
    year: int | None = None
    imdb_id: str | None = None
    arr_instance_id: int | None = None  # istanza Radarr/Sonarr che gestisce il contenuto (source dice quale)
    arr_slug: str | None = None


class MediaResolverAdapter(ABC):
    SOURCE: str  # "filename_parser" | "sonarr" | "radarr" — vedi media_file.resolver_source

    @abstractmethod
    def resolve(self, file_path: str) -> ResolvedMedia | None:
        """None se non risolvibile (filename non parsabile, nessun risultato TMDB) —
        mai un'eccezione per un fallimento atteso, solo per errori veri (rete,
        API key mancante, ecc.), che il chiamante logga e conta come unresolved.
        movie vs tv è dedotto dal resolver stesso (es. guessit), mai passato
        dal chiamante — nessuna configurazione manuale del tipo (SPEC.md)."""
        raise NotImplementedError
