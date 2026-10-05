"""Costruisce le istanze concrete degli adapter a partire dalla
configurazione nel DB.

Vedi CLAUDE.md: solo i mount point vivono in config.yaml, tutto il resto
(tracker, client torrent, credenziali, soglie) vive nel DB ed è editabile
da UI senza restart.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from nazgarr.adapters.image_host.base import ImageHostAdapter
from nazgarr.adapters.image_host.chain import ImageHostChain
from nazgarr.adapters.media_resolver.arr import ArrResolver
from nazgarr.adapters.media_resolver.base import MediaResolverAdapter
from nazgarr.adapters.media_resolver.chain import FirstMatchResolver
from nazgarr.adapters.media_resolver.filename_parser import FilenameParserResolver
from nazgarr.adapters.torrent_client.base import TorrentClientAdapter
from nazgarr.adapters.tracker.base import TrackerAdapter
from nazgarr.core import settings_repo
from nazgarr.core.errors import CodedError
from nazgarr.core.models import TorrentClient, Tracker
from nazgarr.integrations.arr import ArrIndex
from nazgarr.library.tmdb_cache import CachingTMDBClient
from nazgarr.library.tmdb_client import TMDBClient
from nazgarr.plugins import REGISTRY, AdapterContext
from nazgarr.plugins import config as plugin_config

logger = logging.getLogger(__name__)

def _row_config(spec, row) -> dict:
    """I campi di un adapter di un plugin, dalla riga di tracker o client."""
    return plugin_config.with_defaults(spec, plugin_config.loads(getattr(row, "adapter_config_json", None)))


def build_torrent_client_adapter(torrent_client: TorrentClient) -> TorrentClientAdapter:
    spec = REGISTRY.get("torrent_client", torrent_client.adapter_type)
    if spec is None:
        raise ValueError(
            f"adapter_type torrent_client non disponibile: {torrent_client.adapter_type!r} "
            f"(disponibili: {', '.join(sorted(REGISTRY.types('torrent_client')))})"
        )
    return spec.build(AdapterContext(row=torrent_client, config=_row_config(spec, torrent_client)))


def close_adapter(adapter) -> None:
    """Chiude un adapter dopo l'uso (le sue connessioni, il logout dal
    client). Tollerante: un adapter di un plugin o un finto dei test può non
    avere close()."""
    close = getattr(adapter, "close", None)
    if callable(close):
        close()


@contextmanager
def torrent_client(torrent_client: TorrentClient) -> Iterator[TorrentClientAdapter]:
    """L'adapter del client per una sola operazione, chiuso alla fine."""
    adapter = build_torrent_client_adapter(torrent_client)
    try:
        yield adapter
    finally:
        close_adapter(adapter)


@contextmanager
def tracker(tracker_row: Tracker) -> Iterator[TrackerAdapter]:
    """L'adapter del tracker per una sola operazione, chiuso alla fine."""
    adapter = build_tracker_adapter(tracker_row)
    try:
        yield adapter
    finally:
        close_adapter(adapter)


class TmdbApiKeyMissingError(CodedError):
    pass


def plugin_media_resolvers(session: Session) -> list[MediaResolverAdapter]:
    """I resolver dei plugin accesi e configurati, nell'ordine di registrazione."""
    resolvers = []
    for spec in REGISTRY.of_kind("media_resolver"):
        config = plugin_config.usable_global(session, spec)
        if config is None:
            continue
        try:
            resolvers.append(spec.build(AdapterContext(config=config, session=session)))
        except Exception:
            logger.warning("Resolver %s del plugin %s non costruito", spec.adapter_type, spec.plugin, exc_info=True)
    return resolvers


def build_media_resolver(session: Session, arr_index: ArrIndex | None = None) -> MediaResolverAdapter:
    """Prima i resolver dei plugin (se ce ne sono), poi quelli integrati: con
    un indice Radarr/Sonarr non vuoto quello e poi guessit + TMDB come
    ripiego; senza chiave TMDB resta comunque utilizzabile per i soli file
    che Radarr/Sonarr conoscono. TmdbApiKeyMissingError solo se non c'è
    nessuna fonte."""
    plugins = plugin_media_resolvers(session)
    try:
        builtin = _builtin_media_resolver(session, arr_index)
    except TmdbApiKeyMissingError:
        if not plugins:
            raise
        builtin = None
    chain = [*plugins, *([builtin] if builtin is not None else [])]
    return chain[0] if len(chain) == 1 else FirstMatchResolver(chain)


def _builtin_media_resolver(session: Session, arr_index: ArrIndex | None) -> MediaResolverAdapter:
    tmdb_api_key = settings_repo.get_setting(session, "tmdb_api_key")
    has_arr = arr_index is not None and len(arr_index) > 0
    if not tmdb_api_key and not has_arr:
        raise TmdbApiKeyMissingError("tmdb_api_key_missing")

    default_resolver = None
    tv_poster_lookup = None
    if tmdb_api_key:
        raw_tmdb = TMDBClient(api_key=tmdb_api_key)
        default_resolver = FilenameParserResolver(CachingTMDBClient(session, raw_tmdb))
        tv_poster_lookup = raw_tmdb.tv_poster_path
    if not has_arr:
        return default_resolver
    return ArrResolver(arr_index, fallback=default_resolver, tv_poster_lookup=tv_poster_lookup)


def build_tracker_adapter(tracker: Tracker) -> TrackerAdapter:
    spec = REGISTRY.get("tracker", tracker.adapter_type)
    if spec is None:
        raise ValueError(f"adapter_type tracker non supportato: {tracker.adapter_type!r}")
    return spec.build(AdapterContext(row=tracker, config=_row_config(spec, tracker)))


class ImageHostConfigError(CodedError):
    pass


def _build_image_host_adapter(session: Session, spec) -> ImageHostAdapter | None:
    """None = host spento o senza la sua api_key: la catena lo salta."""
    config = plugin_config.usable_global(session, spec)
    if config is None:
        return None
    return spec.build(AdapterContext(config=config, session=session))


def image_host_priority(session: Session) -> list[str]:
    """Gli host registrati nell'ordine scelto (image_host_priority, CSV):
    quelli che l'ordine non nomina ancora (un plugin appena installato) in
    coda, quelli che nomina ma non esistono più (un host tolto, un plugin
    disinstallato) saltati. Acceso o spento lo dice adapter_config."""
    registered = [spec.adapter_type for spec in REGISTRY.of_kind("image_host")]
    raw = settings_repo.get_setting(session, "image_host_priority") or ""
    saved = [key.strip() for key in raw.split(",") if key.strip() in registered]
    return [*dict.fromkeys(saved), *(key for key in registered if key not in saved)]


def image_host_status(session: Session) -> dict:
    """Per l'avviso prima di un upload: gli host utilizzabili (accesi e con
    la chiave), e quelli tolti da un aggiornamento che l'utente usava."""
    order = image_host_priority(session)
    usable = [key for key in order if plugin_config.usable_global(session, REGISTRY.get("image_host", key)) is not None]
    removed = settings_repo.get_setting(session, "image_hosts_removed") or ""
    return {"with_api_key": usable, "usable": usable, "removed": [k for k in removed.split(",") if k], "order": order}


def build_image_host_chain(session: Session) -> ImageHostChain:
    """Gli host accesi e con la chiave, nell'ordine di image_host_priority.
    Se non ne resta nessuno, errore esplicito invece di scoprirlo solo al
    primo upload fallito."""
    specs = [REGISTRY.get("image_host", key) for key in image_host_priority(session)]
    adapters = [a for a in (_build_image_host_adapter(session, spec) for spec in specs) if a is not None]
    if not adapters:
        raise ImageHostConfigError("no_image_host_configured")
    return ImageHostChain(adapters)
