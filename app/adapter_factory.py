"""Costruisce le istanze concrete degli adapter a partire dalla
configurazione nel DB.

Vedi CLAUDE.md: solo i mount point vivono in config.yaml, tutto il resto
(tracker, client torrent, credenziali, soglie) vive nel DB ed è editabile
da UI senza restart.
"""

from sqlalchemy.orm import Session

from app import settings_repo
from app.adapters.image_host.base import ImageHostAdapter
from app.adapters.image_host.chain import ImageHostChain
from app.adapters.image_host.dalexni import DalexniAdapter
from app.adapters.image_host.imgbb import ImgbbAdapter
from app.adapters.image_host.imgbox import ImgboxAdapter
from app.adapters.image_host.lensdump import LensdumpAdapter
from app.adapters.image_host.onlyimage import OnlyimageAdapter
from app.adapters.image_host.pixhost import PixhostAdapter
from app.adapters.image_host.ptpimg import PtpimgAdapter
from app.adapters.image_host.ptscreens import PtscreensAdapter
from app.adapters.image_host.seedpool_cdn import SeedpoolCdnAdapter
from app.adapters.image_host.utppm import UtppmAdapter
from app.adapters.media_resolver.arr import ArrResolver
from app.adapters.media_resolver.base import MediaResolverAdapter
from app.adapters.media_resolver.filename_parser import FilenameParserResolver
from app.adapters.torrent_client.base import TorrentClientAdapter
from app.adapters.torrent_client.qbittorrent import QBittorrentAdapter
from app.adapters.torrent_client.qui import QuiTorrentClientAdapter
from app.adapters.tracker.base import TrackerAdapter, Unit3dTrackerAdapter
from app.api_errors import CodedError
from app.arr import ArrIndex
from app.models import TorrentClient, Tracker
from app.tmdb_cache import CachingTMDBClient
from app.tmdb_client import TMDBClient

DEFAULT_IMAGE_HOST_PRIORITY = [
    "ptpimg", "imgbox", "imgbb", "pixhost",
    "lensdump", "ptscreens", "onlyimage", "dalexni", "utppm", "seedpool_cdn",
]


def build_torrent_client_adapter(torrent_client: TorrentClient) -> TorrentClientAdapter:
    if torrent_client.adapter_type == "qbittorrent":
        return QBittorrentAdapter(
            base_url=torrent_client.base_url,
            username=torrent_client.username,
            password=torrent_client.password,
        )
    if torrent_client.adapter_type == "qui":
        if torrent_client.qui_instance_id is None:
            raise ValueError(f"TorrentClient {torrent_client.id!r} (qui) senza qui_instance_id configurato")
        if not torrent_client.api_token:
            raise ValueError(f"TorrentClient {torrent_client.id!r} (qui) senza api_token configurato")
        return QuiTorrentClientAdapter(
            base_url=torrent_client.base_url,
            api_token=torrent_client.api_token,
            instance_id=torrent_client.qui_instance_id,
        )
    raise ValueError(
        f"adapter_type torrent_client non ancora implementato: {torrent_client.adapter_type!r} "
        "(deluge/transmission/rutorrent pianificati, vedi docs/ROADMAP.md Fase 2)"
    )


class TmdbApiKeyMissingError(CodedError):
    pass


def build_media_resolver(session: Session, arr_index: ArrIndex | None = None) -> MediaResolverAdapter:
    """Con un indice Radarr/Sonarr non vuoto, prima quello e poi guessit +
    TMDB come ripiego; senza chiave TMDB resta comunque utilizzabile per i
    soli file che Radarr/Sonarr conoscono. TmdbApiKeyMissingError solo se
    non c'è nessuna delle due fonti."""
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
    if tracker.adapter_type == "unit3d":
        return Unit3dTrackerAdapter(
            base_url=tracker.base_url,
            api_token=tracker.api_token,
            rate_limit_per_min=tracker.rate_limit_per_min or 30,
            rss_key=tracker.rss_key,
        )
    raise ValueError(f"adapter_type tracker non supportato: {tracker.adapter_type!r}")


class ImageHostConfigError(CodedError):
    pass


def _build_image_host_adapter(session: Session, key: str) -> ImageHostAdapter | None:
    """None = host valido ma non configurato (nessuna api_key impostata),
    saltato in silenzio dalla catena — non un errore finché almeno un
    host della priorità configurata resta utilizzabile."""
    if key == "ptpimg":
        api_key = settings_repo.get_setting(session, "image_host_ptpimg_api_key")
        return PtpimgAdapter(api_key=api_key) if api_key else None
    if key == "imgbb":
        api_key = settings_repo.get_setting(session, "image_host_imgbb_api_key")
        return ImgbbAdapter(api_key=api_key) if api_key else None
    if key == "imgbox":
        return ImgboxAdapter()  # nessuna api_key richiesta (upload anonimi)
    if key == "pixhost":
        return PixhostAdapter()  # nessuna api_key richiesta (upload anonimi)
    if key == "lensdump":
        api_key = settings_repo.get_setting(session, "image_host_lensdump_api_key")
        return LensdumpAdapter(api_key=api_key) if api_key else None
    if key == "ptscreens":
        api_key = settings_repo.get_setting(session, "image_host_ptscreens_api_key")
        return PtscreensAdapter(api_key=api_key) if api_key else None
    if key == "onlyimage":
        api_key = settings_repo.get_setting(session, "image_host_onlyimage_api_key")
        return OnlyimageAdapter(api_key=api_key) if api_key else None
    if key == "dalexni":
        api_key = settings_repo.get_setting(session, "image_host_dalexni_api_key")
        return DalexniAdapter(api_key=api_key) if api_key else None
    if key == "utppm":
        api_key = settings_repo.get_setting(session, "image_host_utppm_api_key")
        return UtppmAdapter(api_key=api_key) if api_key else None
    if key == "seedpool_cdn":
        api_key = settings_repo.get_setting(session, "image_host_seedpool_cdn_api_key")
        return SeedpoolCdnAdapter(api_key=api_key) if api_key else None
    raise ImageHostConfigError("image_host_unknown", key=key)


# Gli host che funzionano solo con una api_key (gli altri: upload anonimi).
KEYED_IMAGE_HOSTS = ("ptpimg", "imgbb", "lensdump", "ptscreens", "onlyimage", "dalexni", "utppm", "seedpool_cdn")


def image_host_status(session: Session) -> dict:
    """Per l'avviso prima di un upload: quali host hanno una api_key e quali
    della priorità configurata sono utilizzabili."""
    raw_priority = settings_repo.get_setting(session, "image_host_priority")
    priority = (
        [k.strip() for k in raw_priority.split(",") if k.strip()] if raw_priority else DEFAULT_IMAGE_HOST_PRIORITY
    )
    usable = []
    for key in priority:
        try:
            if _build_image_host_adapter(session, key) is not None:
                usable.append(key)
        except ImageHostConfigError:
            continue
    keyed = [key for key in KEYED_IMAGE_HOSTS if settings_repo.get_setting(session, f"image_host_{key}_api_key")]
    return {"with_api_key": keyed, "usable": usable}


def build_image_host_chain(session: Session) -> ImageHostChain:
    """Ordine di priorità configurabile via app_settings.image_host_priority
    (CSV, es. 'ptpimg,imgbox,imgbb') — default docs/SPEC.md §9/§17: prova
    PTPImg, poi Imgbox, poi ImgBB. Un host senza api_key configurata viene
    saltato; se la catena risultante è vuota, errore esplicito invece di
    scoprirlo solo al primo upload fallito."""
    raw_priority = settings_repo.get_setting(session, "image_host_priority")
    priority = (
        [k.strip() for k in raw_priority.split(",") if k.strip()] if raw_priority else DEFAULT_IMAGE_HOST_PRIORITY
    )

    adapters = [a for a in (_build_image_host_adapter(session, key) for key in priority) if a is not None]
    if not adapters:
        raise ImageHostConfigError("no_image_host_configured")
    return ImageHostChain(adapters)
