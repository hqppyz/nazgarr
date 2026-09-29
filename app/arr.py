"""Integrazione opzionale Radarr/Sonarr (docs/SPEC.md §6): un indice
costruito una volta per run, in sola lettura, che dà per ogni file che
Radarr/Sonarr conoscono

- la sua identità (tmdb_id, stagione/episodio) senza passare da guessit +
  ricerca TMDB — vedi ArrResolver;
- il torrent da cui è stato importato, se la history lo ricorda: l'evento
  "downloadFolderImported" collega importedPath (file in libreria) e
  droppedPath (file lato torrent) a un downloadId, l'evento "grabbed" con
  lo stesso downloadId dà guid (per UNIT3D via Prowlarr è l'URL di
  download .../torrent/download/<id>.<passkey>, quindi id remoto e link
  al .torrent in un colpo solo) e torrentInfoHash — vedi
  app/matching.py::match_from_history, che così evita la ricerca sul
  tracker.

Mai una dipendenza: nessuna istanza configurata o raggiungibile = indice
vuoto, tutto il resto funziona come prima.

Corrispondenza automatica dei percorsi, nessuna configurazione: i path di
Radarr/Sonarr vivono nel namespace del loro container (es. /data/media/...)
e non coincidono con disk.root_path. Un file corrisponde se le ultime due
parti del percorso (cartella + nome file, case-insensitive) E la
dimensione in byte coincidono — la dimensione esatta rende una collisione
fra file diversi praticamente impossibile, anche fra release dello stesso
titolo. Verificato sul formato delle API reali (Radarr 6.3, Sonarr 4.0),
non ancora sulla corrispondenza con i dischi di un'istanza vera.
"""

import logging
import re
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.models import RadarrInstance, SonarrInstance

logger = logging.getLogger(__name__)

# Codici eventType della history, identici in Radarr v3+ e Sonarr v3+.
EVENT_GRABBED = 1
EVENT_DOWNLOAD_FOLDER_IMPORTED = 3

HISTORY_PAGE_SIZE = 1000
SERIES_WORKERS = 8
HISTORY_WORKERS = 4
DEFAULT_TIMEOUT_SECONDS = 15

# Ultima parte del path di un URL di download UNIT3D: "<id>.<passkey>".
_TORRENT_ID_IN_URL_RE = re.compile(r"/(\d+)\.[^/]+$")
_TMDB_POSTER_RE = re.compile(r"^https?://image\.tmdb\.org/t/p/[^/]+(/[^/]+)$")


def path_key(path: str) -> str:
    """Cartella + nome file, normalizzati — la parte di un percorso che
    resta uguale fra il container di Radarr/Sonarr e questo."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    return "/".join(parts[-2:]).lower()


def host_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url).netloc.lower()
    return host.removeprefix("www.") or None


@dataclass(frozen=True)
class ArrIdentity:
    source: str  # "radarr" | "sonarr" — finisce in media_file.resolver_source
    content_type: str  # "movie" | "tv"
    tmdb_id: int
    season_number: int | None = None
    episode_number: int | None = None
    poster_path: str | None = None  # path relativo TMDB, solo da Radarr (Sonarr dà artwork TVDB)
    title: str | None = None
    year: int | None = None
    imdb_id: str | None = None
    instance_id: int | None = None  # radarr_instance.id / sonarr_instance.id
    slug: str | None = None  # titleSlug della pagina in Radarr/Sonarr


@dataclass(frozen=True)
class ArrGrab:
    tracker_host: str
    torrent_id_remote: str
    download_url: str
    info_hash: str | None
    indexer: str | None


@dataclass
class ArrIndex:
    _identities: dict[tuple[str, int], ArrIdentity] = field(default_factory=dict)
    _grabs: dict[tuple[str, int], ArrGrab] = field(default_factory=dict)
    # (droppedPath, size) -> (importedPath, size): dove è finito in libreria
    # ogni file di un download, anche dopo il rename di Sonarr/Radarr — è ciò
    # che collega i file di un season pack ai singoli episodi importati.
    _imports: dict[tuple[str, int], tuple[str, int]] = field(default_factory=dict)
    # Stessa chiave: QUALE contenuto è stato importato da quel file
    # (content_type, tmdb_id, stagione, episodio). Resta valido anche dopo
    # che il file in libreria è stato sostituito da un upgrade: è ciò che
    # dice "questo vecchio torrent era quel film" (vista Not imported).
    _import_content: dict[tuple[str, int], tuple[str, int, int | None, int | None]] = field(default_factory=dict)
    _by_tmdb: dict[tuple[str, int], ArrIdentity] | None = None

    def add_identity(self, path: str, size: int, identity: ArrIdentity) -> None:
        self._identities.setdefault((path_key(path), size), identity)

    def add_grab(self, path: str, size: int, grab: ArrGrab) -> None:
        # History dalla più recente: il primo grab visto per un file è quello
        # da cui proviene la versione attuale, non uno precedente poi sostituito.
        self._grabs.setdefault((path_key(path), size), grab)

    def identity_for(self, path: str, size: int) -> ArrIdentity | None:
        return self._identities.get((path_key(path), size))

    def details_for(self, content_type: str, tmdb_id: int) -> ArrIdentity | None:
        """Un'identità qualunque con quel tmdb_id: titolo, anno e (film)
        poster valgono per tutti i file dello stesso contenuto."""
        if self._by_tmdb is None:
            self._by_tmdb = {}
            for identity in self._identities.values():
                self._by_tmdb.setdefault((identity.content_type, identity.tmdb_id), identity)
        return self._by_tmdb.get((content_type, tmdb_id))

    def grab_for(self, path: str, size: int) -> ArrGrab | None:
        return self._grabs.get((path_key(path), size))

    def add_import(self, dropped_path: str, imported_path: str, size: int,
                   content: tuple[str, int, int | None, int | None] | None = None) -> None:
        key = (path_key(dropped_path), size)
        self._imports.setdefault(key, (path_key(imported_path), size))
        if content is not None:
            self._import_content.setdefault(key, content)

    def imported_content_for(self, dropped_path: str, size: int) -> tuple[str, int, int | None, int | None] | None:
        return self._import_content.get((path_key(dropped_path), size))

    def imported_for(self, dropped_path: str, size: int) -> tuple[str, int] | None:
        """Chiave (path_key, size) del file in libreria importato da questo
        file del download — da cercare fra i media_file con la stessa chiave."""
        return self._imports.get((path_key(dropped_path), size))

    def __len__(self) -> int:
        return len(self._identities) + len(self._grabs)

    @property
    def counts(self) -> dict[str, int]:
        return {"identities": len(self._identities), "grabs": len(self._grabs), "imports": len(self._imports)}


class ArrApi:
    """Client minimale v3, solo GET. `client` iniettabile per i test."""

    def __init__(self, instance: RadarrInstance | SonarrInstance, client: httpx.Client | None = None):
        auth = (
            (instance.basic_auth_username, instance.basic_auth_password or "")
            if instance.basic_auth_username
            else None
        )
        self.label = instance.label
        self.instance_id = instance.id
        self._client = client or httpx.Client(
            base_url=instance.base_url.rstrip("/"),
            headers={"X-Api-Key": instance.api_key},
            timeout=instance.timeout_seconds or DEFAULT_TIMEOUT_SECONDS,
            auth=auth,
        )

    def get(self, path: str, **params) -> object:
        response = self._client.get(path, params=params or None)
        response.raise_for_status()
        return response.json()

    def _history_page(self, event_type: int, page: int) -> dict:
        return self.get(
            "/api/v3/history", page=page, pageSize=HISTORY_PAGE_SIZE, eventType=event_type,
            sortKey="date", sortDirection="descending",
        )

    def history(self, event_type: int) -> Iterator[dict]:
        """Ogni evento di quel tipo, dal più recente. La prima pagina dà il
        totale, le altre si scaricano HISTORY_WORKERS alla volta (era la parte
        più lenta dell'indice: decine di pagine in fila), in ordine."""
        first = self._history_page(event_type, 1)
        yield from first.get("records") or []
        pages = -(-(first.get("totalRecords") or 0) // HISTORY_PAGE_SIZE)  # arrotondato per eccesso
        if pages <= 1:
            return
        with ThreadPoolExecutor(max_workers=HISTORY_WORKERS) as pool:
            for body in pool.map(lambda page: self._history_page(event_type, page), range(2, pages + 1)):
                yield from body.get("records") or []


def _grab_from_event(event: dict) -> ArrGrab | None:
    data = event.get("data") or {}
    guid = data.get("guid")
    match = _TORRENT_ID_IN_URL_RE.search(urlsplit(guid).path) if guid else None
    host = host_of(guid)
    if match is None or host is None:
        return None  # indexer non UNIT3D o guid non un URL di download: nessun id ricavabile
    return ArrGrab(
        tracker_host=host,
        torrent_id_remote=match.group(1),
        download_url=guid,
        info_hash=(data.get("torrentInfoHash") or event.get("downloadId") or "").lower() or None,
        indexer=data.get("indexer"),
    )


def _index_history(api: ArrApi, index: ArrIndex, content_of: Callable[[dict], tuple | None] = lambda e: None) -> None:
    grabs_by_download_id: dict[str, ArrGrab] = {}
    for event in api.history(EVENT_GRABBED):
        download_id = event.get("downloadId")
        grab = _grab_from_event(event)
        if download_id and grab is not None:
            grabs_by_download_id.setdefault(download_id, grab)

    for event in api.history(EVENT_DOWNLOAD_FOLDER_IMPORTED):
        grab = grabs_by_download_id.get(event.get("downloadId") or "")
        data = event.get("data") or {}
        try:
            size = int(data.get("size"))
        except (TypeError, ValueError):
            continue
        imported, dropped = data.get("importedPath"), data.get("droppedPath")
        if imported and dropped:
            index.add_import(dropped, imported, size, content_of(event))
        if grab is None:
            continue
        for path in (imported, dropped):
            if path:
                index.add_grab(path, size, grab)


def _tmdb_poster_path(item: dict) -> str | None:
    for image in item.get("images") or []:
        if image.get("coverType") == "poster":
            match = _TMDB_POSTER_RE.match(image.get("remoteUrl") or "")
            if match:
                return match.group(1)
    return None


def _index_radarr(api: ArrApi, index: ArrIndex) -> None:
    movies = api.get("/api/v3/movie")
    # Anche i film senza file (sostituiti, cancellati): la history li cita per id.
    content = {m["id"]: ("movie", m["tmdbId"], None, None) for m in movies if m.get("id") and m.get("tmdbId")}
    for movie in movies:
        movie_file = movie.get("movieFile") or {}
        if not (movie.get("tmdbId") and movie_file.get("path") and movie_file.get("size")):
            continue
        index.add_identity(
            movie_file["path"], movie_file["size"],
            ArrIdentity(
                source="radarr", content_type="movie", tmdb_id=movie["tmdbId"],
                poster_path=_tmdb_poster_path(movie), title=movie.get("title"), year=movie.get("year") or None,
                imdb_id=movie.get("imdbId") or None, instance_id=api.instance_id, slug=movie.get("titleSlug"),
            ),
        )
    _index_history(api, index, lambda event: content.get(event.get("movieId")))


def _series_files(api: ArrApi, series: dict) -> tuple[dict, list[dict], list[dict]]:
    return (
        series,
        api.get("/api/v3/episode", seriesId=series["id"]),
        api.get("/api/v3/episodefile", seriesId=series["id"]),
    )


def _index_sonarr(api: ArrApi, index: ArrIndex) -> None:
    # Episodi e file di ogni serie: due GET per serie, fatte SERIES_WORKERS
    # alla volta (rete locale) — sequenziali costavano ~18s su ~110 serie.
    # L'indice si aggiorna solo qui, nel thread chiamante.
    series_list = [s for s in api.get("/api/v3/series") if s.get("tmdbId")]  # senza tmdbId: resolver di default
    with ThreadPoolExecutor(max_workers=SERIES_WORKERS) as pool:
        fetched = list(pool.map(lambda s: _series_files(api, s), series_list))
    content: dict[int, tuple] = {}  # episode id -> contenuto, per la history
    for series, episodes, episode_files in fetched:
        episode_by_file: dict[int, tuple[int, int]] = {}
        for episode in episodes:
            if episode.get("id") and episode.get("seasonNumber") is not None:
                content[episode["id"]] = ("tv", series["tmdbId"], episode["seasonNumber"], episode.get("episodeNumber"))
            file_id = episode.get("episodeFileId")
            if file_id:
                # File multi-episodio: vale il primo, come fa FilenameParserResolver.
                key = (episode["seasonNumber"], episode["episodeNumber"])
                episode_by_file[file_id] = min(episode_by_file.get(file_id, key), key)
        for episode_file in episode_files:
            numbers = episode_by_file.get(episode_file.get("id"))
            if numbers is None or not episode_file.get("path") or not episode_file.get("size"):
                continue
            index.add_identity(
                episode_file["path"], episode_file["size"],
                ArrIdentity(
                    source="sonarr", content_type="tv", tmdb_id=series["tmdbId"],
                    season_number=numbers[0], episode_number=numbers[1],
                    title=series.get("title"), year=series.get("year") or None,
                    imdb_id=series.get("imdbId") or None, instance_id=api.instance_id, slug=series.get("titleSlug"),
                ),
            )
    _index_history(api, index, lambda event: content.get(event.get("episodeId")))


def build_arr_index(session: Session, api_factory: Callable[..., ArrApi] = ArrApi) -> ArrIndex:
    """Un'istanza irraggiungibile o con una risposta inattesa viene loggata
    e saltata, mai un errore della run: l'integrazione resta opzionale.
    Istanze con priority più alta indicizzate per prime, quindi vincono se
    due istanze conoscono lo stesso file."""
    index = ArrIndex()
    instances: list[tuple[RadarrInstance | SonarrInstance, Callable[[ArrApi, ArrIndex], None]]] = []
    for model, indexer in ((RadarrInstance, _index_radarr), (SonarrInstance, _index_sonarr)):
        for instance in session.query(model).filter_by(enabled=True).all():
            instances.append((instance, indexer))
    instances.sort(key=lambda pair: -(pair[0].priority or 0))

    for instance, indexer in instances:
        try:
            indexer(api_factory(instance), index)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            logger.warning("Istanza %r (%s) non indicizzata", instance.label, instance.base_url, exc_info=True)
    return index

