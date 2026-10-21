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
  nazgarr/reseed/matching.py::match_from_history, che così evita la ricerca sul
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

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from nazgarr.core import http_limits, net_guard
from nazgarr.core.models import RadarrInstance, SonarrInstance

logger = logging.getLogger(__name__)

# Codici eventType della history, identici in Radarr v3+ e Sonarr v3+.
EVENT_GRABBED = 1
EVENT_DOWNLOAD_FOLDER_IMPORTED = 3

HISTORY_PAGE_SIZE = 1000
SERIES_WORKERS = 8
HISTORY_WORKERS = 4
DEFAULT_TIMEOUT_SECONDS = 15
# Il timeout più lungo accettato dall'API (5 minuti, audit 2026-10-18).
TIMEOUT_MAX_SECONDS = 300
# Una risposta di Radarr/Sonarr letta con un tetto (nazgarr/core/http_limits.py):
# l'elenco dei film di Radarr è la più grande, qualche KB per film, quindi
# decine di MB per una libreria molto grande; ben sotto, e lontano da un
# gzip che si espande a GB nel processo unico (audit 2026-10-18).
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
RESPONSE_DEADLINE_SECONDS = 300.0

# Ultima parte del path di un URL di download UNIT3D: "<id>.<passkey>".
_TORRENT_ID_IN_URL_RE = re.compile(r"/(\d+)\.[^/]+$")
_TMDB_POSTER_RE = re.compile(r"^https?://image\.tmdb\.org/t/p/[^/]+(/[^/]+)$")


def path_key(path: str) -> str:
    """Cartella + nome file, normalizzati — la parte di un percorso che
    resta uguale fra il container di Radarr/Sonarr e questo."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    return "/".join(parts[-2:]).lower()


_DEFAULT_PORTS = {"http": 80, "https": 443}


def host_of(url: str | None) -> str | None:
    """L'host di un URL per confrontare un grab della history (guid) col
    tracker: come host_of_url di nazgarr/adapters/tracker/base.py (netloc in
    minuscolo, senza "www."), ma senza la porta di default dello schema
    (":443" su https, ":80" su http), che un guid può scrivere e base_url no:
    altrimenti la scorciatoia della history si perdeva e il matching tornava
    a cercare sul tracker (audit 2026-10-18). Una porta diversa resta: i
    controlli di sicurezza del tracker usano host_of_url, mai questa."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = parts.netloc.lower()
    if port is not None and _DEFAULT_PORTS.get(parts.scheme.lower()) == port:
        host = host.rsplit(":", 1)[0]
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
    # Nome originale della release (sceneName, o il nome del file scaricato):
    # quello da cui un upload ricava risoluzione, sorgente, codec e gruppo,
    # anche dopo il rename in libreria.
    scene_name: str | None = None


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


def timeout_of(instance) -> int:
    """Il timeout salvato di un'istanza, o quello di default se manca o non è
    positivo, e al massimo TIMEOUT_MAX_SECONDS: una riga di prima dei limiti
    dell'API (audit 2026-10-18) con un valore negativo faceva fallire ogni
    chiamata. È anche quello che l'API mostra (ArrInstanceResponse), così il
    form rimanda un valore che passa la validazione."""
    value = instance.timeout_seconds
    if not isinstance(value, int) or value <= 0:
        return DEFAULT_TIMEOUT_SECONDS
    return min(value, TIMEOUT_MAX_SECONDS)


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
        self.base_url = instance.base_url.rstrip("/")
        self._checked = False
        # Mai un indirizzo vietato nemmeno se il DNS cambia dopo il controllo (net_guard).
        self._client = client or net_guard.http_client(
            base_url=self.base_url,
            headers={"X-Api-Key": instance.api_key},
            timeout=timeout_of(instance),
            auth=auth,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def get(self, path: str, **params) -> object:
        """Il JSON di una GET, letto in streaming con un tetto
        (MAX_RESPONSE_BYTES, RESPONSE_DEADLINE_SECONDS): prima httpx lo
        scaricava e decomprimeva tutto in memoria. net_guard una volta per
        indice (quando l'API fa la prima richiesta), non solo quando
        l'indirizzo si salva: un nome che ora si risolve nei metadati del
        cloud non si chiama."""
        if not self._checked:
            net_guard.check_url(self.base_url)  # ForbiddenDestination è un ValueError: istanza saltata
            self._checked = True
        with self._client.stream("GET", path, params=params or None,
                                 headers={"Accept-Encoding": http_limits.ACCEPT_ENCODING}) as response:
            response.raise_for_status()
            try:
                body = http_limits.read_limited(response, MAX_RESPONSE_BYTES,
                                                time.monotonic() + RESPONSE_DEADLINE_SECONDS)
            except http_limits.ResponseLimitExceeded as exc:
                raise ValueError(f"{self.label} sent an answer {exc}") from exc
        return json.loads(body)

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

    def history_newer(self, event_type: int, newest_id: int) -> Iterator[dict]:
        """Solo gli eventi più nuovi di newest_id (gli id della history
        crescono), dal più recente: una pagina alla volta fino al primo già
        letto, di solito la prima e basta. _HistoryReset se la history non
        continua quella letta (svuotata, o un'altra istanza allo stesso
        indirizzo: il più recente è più vecchio di newest_id) o se un evento
        non ha id: va riletta tutta."""
        page = 1
        while True:
            body = self._history_page(event_type, page)
            records = body.get("records") or []
            if page == 1 and newest_id > 0 and (not records or (_record_id(records[0]) or 0) < newest_id):
                raise _HistoryReset
            for record in records:
                record_id = _record_id(record)
                if record_id is None:
                    raise _HistoryReset
                if record_id <= newest_id:
                    return
                yield record
            if not records or page * HISTORY_PAGE_SIZE >= (body.get("totalRecords") or 0):
                return
            page += 1


class _HistoryReset(Exception):
    """La history di un'istanza non continua quella già letta."""


def _record_id(record: dict) -> int | None:
    value = record.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# La history già letta di ogni istanza (audit 2026-10-18): prima ogni indice
# la riscaricava tutta, grab e import, a ogni run, a ogni "Aggiorna" di Not
# imported (sincrono nella richiesta) e a ogni indice degli upload scaduto;
# decine di secondi per un'istanza vecchia e grande. Ora si legge tutta una
# volta per processo, poi solo quello che è arrivato dopo (history_newer),
# per tutti quelli che costruiscono un indice. In memoria solo quello che
# l'indice usa: il grab per downloadId, e per ogni import downloadId, le due
# chiavi dei percorsi, la dimensione e il film o episodio. Un evento della
# history non cambia mai: uno tolto là resta qui, ed è comunque successo.
# Chiave: (DB, tipo, id dell'istanza, indirizzo, tipo di evento); un
# indirizzo cambiato, o un'istanza spenta o tolta, riparte da capo.
@dataclass(frozen=True)
class _CachedHistory:
    newest_id: int
    value: object  # dict di grab o lista di import: mai modificati dopo


_history_cache: dict[tuple, _CachedHistory] = {}
_history_locks: dict[tuple, threading.Lock] = {}
_history_guard = threading.Lock()


class _Ids:
    """L'id più recente degli eventi che passano, mentre passano: la history
    resta letta a pagine, mai tutta in memoria in una volta."""

    def __init__(self, newest: int = 0):
        self.newest, self.complete, self.seen = newest, True, 0

    def track(self, records: Iterator[dict]) -> Iterator[dict]:
        for record in records:
            record_id = _record_id(record)
            if record_id is None:
                self.complete = False  # senza id non si sa da dove ripartire: niente cache
            elif record_id > self.newest:
                self.newest = record_id
            self.seen += 1
            yield record


def _history_value(api, key: tuple | None, event_type: int, parse: Callable[[Iterator[dict]], object],
                   merge: Callable[[object, object], object]):
    """Quello che parse ricava dalla history di quel tipo: tutta la prima
    volta, poi solo gli eventi nuovi, uniti con merge(nuovi, già letti)."""
    if key is None:
        return parse(api.history(event_type))
    full_key = (*key, event_type)
    with _history_guard:
        lock = _history_locks.setdefault(full_key, threading.Lock())
    with lock:  # due indici insieme della stessa istanza: il secondo legge quello che il primo ha appena preso
        cached = _history_cache.get(full_key)
        value = None
        if cached is not None:
            ids = _Ids(cached.newest_id)
            try:
                new = parse(ids.track(api.history_newer(event_type, cached.newest_id)))
                value = merge(new, cached.value) if ids.seen else cached.value
            except _HistoryReset:
                logger.info("History di %r non continua quella letta: riletta tutta", getattr(api, "label", "?"))
                cached = None
        if cached is None:
            ids = _Ids()
            value = parse(ids.track(api.history(event_type)))
        # Si scrive sotto il guard, come legge _forget_history: un indice di
        # un altro thread che inserisce una chiave mentre quello scorre il
        # dizionario era un RuntimeError a metà run. E solo se la chiave è
        # ancora questa: tolta intanto (istanza spenta o cambiata), un indice
        # partito prima non la rimette (e non tocca quella che un indice
        # partito dopo, con un lock nuovo, ha già scritto).
        with _history_guard:
            if _history_locks.get(full_key) is not lock:
                pass
            elif ids.complete:
                _history_cache[full_key] = _CachedHistory(ids.newest, value)
            else:
                _history_cache.pop(full_key, None)
        return value


def _forget_history(db: str, keep: set[tuple]) -> None:
    """Toglie la history delle istanze di quel DB che non si indicizzano più."""
    with _history_guard:
        # Anche le chiavi di una prima lettura in corso, che hanno solo il lock.
        for full_key in [k for k in {*_history_cache, *_history_locks} if k[0] == db and k[:4] not in keep]:
            _history_cache.pop(full_key, None)
            _history_locks.pop(full_key, None)


def clear_history_cache() -> None:
    with _history_guard:
        _history_cache.clear()
        _history_locks.clear()


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


def _grabs_of(events: Iterator[dict]) -> dict[str, ArrGrab]:
    """downloadId -> grab, dal più recente: vince il primo visto."""
    grabs: dict[str, ArrGrab] = {}
    for event in events:
        download_id = event.get("downloadId")
        grab = _grab_from_event(event)
        if download_id and grab is not None:
            grabs.setdefault(download_id, grab)
    return grabs


def _imports_of(events: Iterator[dict], ref_field: str) -> list[tuple]:
    """(downloadId, chiave del file importato, chiave del file scaricato,
    dimensione, id del film o dell'episodio) per ogni import, dal più recente."""
    rows = []
    for event in events:
        data = event.get("data") or {}
        try:
            size = int(data.get("size"))
        except (TypeError, ValueError):
            continue
        imported, dropped = data.get("importedPath"), data.get("droppedPath")
        rows.append((event.get("downloadId") or "", path_key(imported) if imported else None,
                     path_key(dropped) if dropped else None, size, event.get(ref_field)))
    return rows


def _index_history(api: ArrApi, index: ArrIndex, ref_field: str, content: dict, history_key: tuple | None = None
                   ) -> None:
    # I nuovi sono più recenti: vincono sui grab già letti, e gli import
    # vanno davanti (l'indice tiene il primo che vede).
    grabs = _history_value(api, history_key, EVENT_GRABBED, _grabs_of, lambda new, old: {**old, **new})
    imports = _history_value(api, history_key, EVENT_DOWNLOAD_FOLDER_IMPORTED,
                             lambda events: _imports_of(events, ref_field), lambda new, old: new + old)
    for download_id, imported, dropped, size, ref in imports:
        grab = grabs.get(download_id)
        if imported and dropped:
            index.add_import(dropped, imported, size, content.get(ref))
        if grab is None:
            continue
        for path in (imported, dropped):
            if path:
                index.add_grab(path, size, grab)


def tmdb_poster_path(item: dict) -> str | None:
    for image in item.get("images") or []:
        if image.get("coverType") == "poster":
            match = _TMDB_POSTER_RE.match(image.get("remoteUrl") or "")
            if match:
                return match.group(1)
    return None


def _scene_name(media_file: dict) -> str | None:
    """sceneName se Radarr/Sonarr l'hanno registrato, altrimenti il nome del
    file originale (originalFilePath, senza cartelle né estensione)."""
    if media_file.get("sceneName"):
        return media_file["sceneName"]
    original = media_file.get("originalFilePath")
    if not original:
        return None
    name = original.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def _index_radarr(api: ArrApi, index: ArrIndex, history_key: tuple | None = None) -> None:
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
                poster_path=tmdb_poster_path(movie), title=movie.get("title"), year=movie.get("year") or None,
                imdb_id=movie.get("imdbId") or None, instance_id=api.instance_id, slug=movie.get("titleSlug"),
                scene_name=_scene_name(movie_file),
            ),
        )
    _index_history(api, index, "movieId", content, history_key)


def _series_files(api: ArrApi, series: dict) -> tuple[dict, list[dict], list[dict]]:
    return (
        series,
        api.get("/api/v3/episode", seriesId=series["id"]),
        api.get("/api/v3/episodefile", seriesId=series["id"]),
    )


def _index_sonarr(api: ArrApi, index: ArrIndex, history_key: tuple | None = None) -> None:
    # Episodi e file di ogni serie: due GET per serie, fatte SERIES_WORKERS
    # alla volta (rete locale) — sequenziali costavano ~18s su ~110 serie.
    # L'indice si aggiorna solo qui, nel thread chiamante.
    series_list = [s for s in api.get("/api/v3/series") if s.get("tmdbId")]  # senza tmdbId: resolver di default
    content: dict[int, tuple] = {}  # episode id -> contenuto, per la history
    # Ogni serie si indicizza appena arriva e la sua risposta si lascia
    # andare: in memoria restano le poche serie scaricate in anticipo, non
    # gli episodi e i file di tutta la libreria (audit 2026-10-18).
    with ThreadPoolExecutor(max_workers=SERIES_WORKERS) as pool:
        for series, episodes, episode_files in pool.map(lambda s: _series_files(api, s), series_list):
            _index_series(api, index, content, series, episodes, episode_files)
    _index_history(api, index, "episodeId", content, history_key)


def _index_series(api: ArrApi, index: ArrIndex, content: dict[int, tuple], series: dict, episodes: list[dict],
                  episode_files: list[dict]) -> None:
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
                scene_name=_scene_name(episode_file),
            ),
        )


def build_arr_index(session: Session, api_factory: Callable[..., ArrApi] = ArrApi) -> ArrIndex:
    """Un'istanza irraggiungibile o con una risposta inattesa viene loggata
    e saltata, mai un errore della run: l'integrazione resta opzionale.
    Istanze con priority più alta indicizzate per prime, quindi vincono se
    due istanze conoscono lo stesso file."""
    index = ArrIndex()
    instances: list[tuple[RadarrInstance | SonarrInstance, Callable[..., None]]] = []
    for model, indexer in ((RadarrInstance, _index_radarr), (SonarrInstance, _index_sonarr)):
        for instance in session.query(model).filter_by(enabled=True).all():
            instances.append((instance, indexer))
    instances.sort(key=lambda pair: -(pair[0].priority or 0))
    # La history già letta si riusa (_history_value): per istanza di questo DB.
    db = str(session.get_bind().url)
    keys = [(db, instance.__tablename__, instance.id, instance.base_url) for instance, _ in instances]
    _forget_history(db, set(keys))

    for (instance, indexer), key in zip(instances, keys, strict=True):
        api = None
        try:
            api = api_factory(instance)
            # Un'API finta dei test (senza history_newer) si legge tutta ogni volta.
            indexer(api, index, key if hasattr(api, "history_newer") else None)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            logger.warning("Istanza %r (%s) non indicizzata", instance.label, instance.base_url, exc_info=True)
        finally:
            close_api(api)
    return index


def close_api(api) -> None:
    """Chiude un ArrApi (o un finto dei test, che può non avere close)."""
    close = getattr(api, "close", None)
    if callable(close):
        close()

