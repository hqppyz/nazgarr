"""Costruisce le istanze concrete degli adapter a partire dalla
configurazione nel DB.

Vedi CLAUDE.md: solo i mount point vivono in config.yaml, tutto il resto
(tracker, client torrent, credenziali, soglie) vive nel DB ed è editabile
da UI senza restart.
"""

import logging

from sqlalchemy.orm import Session

from app import settings_repo
from app.adapters.image_host.base import ImageHostAdapter
from app.adapters.image_host.chain import ImageHostChain
from app.adapters.media_resolver.arr import ArrResolver
from app.adapters.media_resolver.base import MediaResolverAdapter
from app.adapters.media_resolver.chain import FirstMatchResolver
from app.adapters.media_resolver.filename_parser import FilenameParserResolver
from app.adapters.torrent_client.base import TorrentClientAdapter
from app.adapters.tracker.base import TrackerAdapter
from app.api_errors import CodedError
from app.arr import ArrIndex
from app.models import TorrentClient, Tracker
from app.plugins import REGISTRY, AdapterContext
from app.plugins import config as plugin_config
from app.tmdb_cache import CachingTMDBClient
from app.tmdb_client import TMDBClient

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_HOST_PRIORITY = [
    "ptpimg", "imgbox", "imgbb", "pixhost",
    "lensdump", "ptscreens", "onlyimage", "dalexni", "utppm", "seedpool_cdn",
]


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


def _image_host_config(session: Session, spec) -> dict | None:
    """I valori dei campi di un host dalle impostazioni
    (image_host_<host>_<campo>, es. image_host_ptpimg_api_key); None se ne
    manca uno obbligatorio."""
    config = {}
    for field in spec.config_fields:
        value = settings_repo.get_setting(session, f"image_host_{spec.adapter_type}_{field.key}")
        if value in (None, "") and field.required:
            return None
        config[field.key] = value if value not in (None, "") else field.default
    return config


def _build_image_host_adapter(session: Session, key: str) -> ImageHostAdapter | None:
    """None = host valido ma non configurato (nessuna api_key impostata),
    saltato in silenzio dalla catena — non un errore finché almeno un
    host della priorità configurata resta utilizzabile."""
    spec = REGISTRY.get("image_host", key)
    if spec is None:
        raise ImageHostConfigError("image_host_unknown", key=key)
    # Integrati: la loro chiave nelle impostazioni; plugin: adapter_config.
    config = plugin_config.usable_global(session, spec) if spec.plugin else _image_host_config(session, spec)
    if config is None:
        return None
    return spec.build(AdapterContext(config=config, session=session))


def keyed_image_hosts() -> list[str]:
    """Gli host che funzionano solo con una api_key (gli altri: upload anonimi)."""
    return [spec.adapter_type for spec in REGISTRY.of_kind("image_host") if spec.required_fields]


def _has_key(session: Session, key: str) -> bool:
    spec = REGISTRY.get("image_host", key)
    if spec is not None and spec.plugin:
        return plugin_config.usable_global(session, spec) is not None
    return bool(settings_repo.get_setting(session, f"image_host_{key}_api_key"))


def image_host_status(session: Session) -> dict:
    """Per l'avviso prima di un upload: quali host hanno una api_key e quali
    della priorità configurata sono utilizzabili."""
    priority = image_host_priority(session)
    usable = []
    for key in priority:
        try:
            if _build_image_host_adapter(session, key) is not None:
                usable.append(key)
        except ImageHostConfigError:
            continue
    keyed = [key for key in keyed_image_hosts() if _has_key(session, key)]
    return {"with_api_key": keyed, "usable": usable}


def image_host_priority(session: Session) -> list[str]:
    """La priorità salvata (o quella di default), con in coda gli host dei
    plugin che non ci sono ancora."""
    raw_priority = settings_repo.get_setting(session, "image_host_priority")
    priority = (
        [k.strip() for k in raw_priority.split(",") if k.strip()] if raw_priority else DEFAULT_IMAGE_HOST_PRIORITY
    )
    extra = [spec.adapter_type for spec in REGISTRY.of_kind("image_host") if spec.plugin]
    return [*priority, *(key for key in extra if key not in priority)]


def build_image_host_chain(session: Session) -> ImageHostChain:
    """Ordine di priorità configurabile via app_settings.image_host_priority
    (CSV, es. 'ptpimg,imgbox,imgbb') — default docs/SPEC.md §9/§17: prova
    PTPImg, poi Imgbox, poi ImgBB. Un host senza api_key configurata viene
    saltato; se la catena risultante è vuota, errore esplicito invece di
    scoprirlo solo al primo upload fallito."""
    priority = image_host_priority(session)

    adapters = [a for a in (_build_image_host_adapter(session, key) for key in priority) if a is not None]
    if not adapters:
        raise ImageHostConfigError("no_image_host_configured")
    return ImageHostChain(adapters)
