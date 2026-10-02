"""SDK pubblico di Nazgarr per i plugin (docs/ROADMAP.md Fase 10, docs/SDK.md).

Un plugin importa solo da qui, mai da app.*: questo modulo è il contratto
stabile, versionato da SDK_VERSION (semver: un cambio incompatibile alza la
major). Un plugin dichiara con quali versioni funziona.

Un plugin può registrare adapter (tracker, client torrent, resolver dei
media, host di immagini, notifiche). Non tocca mai file né client
direttamente: le azioni che cambiano qualcosa passano sempre dalla coda di
approvazione dell'utente.
"""

from nazgarr.adapters.image_host.base import ImageHostAdapter, ImageHostError
from nazgarr.adapters.media_resolver.base import MediaResolverAdapter, ResolvedMedia
from nazgarr.adapters.notification.base import Notification, NotificationAdapter, NotificationError
from nazgarr.adapters.torrent_client.base import (
    ClientTorrentFileInfo,
    ClientTorrentInfo,
    TorrentAddTimeoutError,
    TorrentAlreadyInClientError,
    TorrentClientAdapter,
    TorrentStatus,
)
from nazgarr.adapters.tracker.base import (
    NotSupportedError,
    TorrentCandidate,
    TorrentRecord,
    TrackerAdapter,
    TrackerRateLimitedError,
    UploadedTorrent,
    UploadError,
    UploadFields,
)
from nazgarr.plugins.registry import KINDS, AdapterContext, AdapterSpec, ConfigField, register

SDK_VERSION = "1.0.0"

__all__ = [
    "KINDS", "SDK_VERSION", "AdapterContext", "AdapterSpec", "ClientTorrentFileInfo", "ClientTorrentInfo",
    "ConfigField", "ImageHostAdapter", "ImageHostError", "MediaResolverAdapter", "NotSupportedError",
    "Notification", "NotificationAdapter", "NotificationError",
    "ResolvedMedia", "TorrentAddTimeoutError", "TorrentAlreadyInClientError", "TorrentCandidate",
    "TorrentClientAdapter", "TorrentRecord", "TorrentStatus", "TrackerAdapter", "TrackerRateLimitedError",
    "UploadError", "UploadFields", "UploadedTorrent", "register",
]
