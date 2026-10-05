"""Gli adapter integrati, iscritti al registro come farebbe un plugin
(nazgarr/plugins/registry.py). Tracker e client leggono le colonne che hanno
sempre avuto (ctx.row); gli host di immagini la loro api_key dalle
impostazioni (nazgarr/integrations/adapter_factory.py)."""

from nazgarr.adapters.image_host.dalexni import DalexniAdapter
from nazgarr.adapters.image_host.imgbb import ImgbbAdapter
from nazgarr.adapters.image_host.imgbox import ImgboxAdapter
from nazgarr.adapters.image_host.lensdump import LensdumpAdapter
from nazgarr.adapters.image_host.onlyimage import OnlyimageAdapter
from nazgarr.adapters.image_host.pixhost import PixhostAdapter
from nazgarr.adapters.image_host.ptpimg import PtpimgAdapter
from nazgarr.adapters.image_host.ptscreens import PtscreensAdapter
from nazgarr.adapters.image_host.seedpool_cdn import SeedpoolCdnAdapter
from nazgarr.adapters.image_host.utppm import UtppmAdapter
from nazgarr.adapters.notification.discord import DiscordNotificationAdapter
from nazgarr.adapters.notification.telegram import TelegramNotificationAdapter
from nazgarr.adapters.torrent_client.deluge import DelugeAdapter
from nazgarr.adapters.torrent_client.qbittorrent import QBittorrentAdapter
from nazgarr.adapters.torrent_client.qui import QuiTorrentClientAdapter
from nazgarr.adapters.torrent_client.rtorrent import RTorrentAdapter
from nazgarr.adapters.torrent_client.transmission import TransmissionAdapter
from nazgarr.adapters.tracker.base import Unit3dTrackerAdapter
from nazgarr.plugins.registry import AdapterContext, AdapterSpec, ConfigField, register

API_KEY = ConfigField("api_key", "API key", type="secret", required=True)


def _qbittorrent(ctx: AdapterContext) -> QBittorrentAdapter:
    tc = ctx.row
    return QBittorrentAdapter(base_url=tc.base_url, username=tc.username, password=tc.password)


def _qui(ctx: AdapterContext) -> QuiTorrentClientAdapter:
    tc = ctx.row
    if tc.qui_instance_id is None:
        raise ValueError(f"TorrentClient {tc.id!r} (qui) senza qui_instance_id configurato")
    if not tc.api_token:
        raise ValueError(f"TorrentClient {tc.id!r} (qui) senza api_token configurato")
    return QuiTorrentClientAdapter(base_url=tc.base_url, api_token=tc.api_token, instance_id=tc.qui_instance_id)


def _deluge(ctx: AdapterContext) -> DelugeAdapter:
    # La Web UI di Deluge ha solo la password, nessun utente.
    return DelugeAdapter(base_url=ctx.row.base_url, password=ctx.row.password)


def _transmission(ctx: AdapterContext) -> TransmissionAdapter:
    tc = ctx.row
    return TransmissionAdapter(base_url=tc.base_url, username=tc.username, password=tc.password)


def _rtorrent(ctx: AdapterContext) -> RTorrentAdapter:
    tc = ctx.row
    return RTorrentAdapter(base_url=tc.base_url, username=tc.username, password=tc.password)


def _unit3d(ctx: AdapterContext) -> Unit3dTrackerAdapter:
    tracker = ctx.row
    return Unit3dTrackerAdapter(
        base_url=tracker.base_url, api_token=tracker.api_token,
        rate_limit_per_min=tracker.rate_limit_per_min or 30, rss_key=tracker.rss_key, shared=True,
    )


def _keyed(cls):
    return lambda ctx: cls(api_key=ctx.config["api_key"])


register(AdapterSpec("torrent_client", "qbittorrent", "qBittorrent", _qbittorrent))
register(AdapterSpec("torrent_client", "qui", "qui", _qui))
register(AdapterSpec("torrent_client", "deluge", "Deluge", _deluge))
register(AdapterSpec("torrent_client", "transmission", "Transmission", _transmission))
register(AdapterSpec("torrent_client", "rutorrent", "rTorrent / ruTorrent", _rtorrent))
register(AdapterSpec("tracker", "unit3d", "UNIT3D", _unit3d))

for adapter_type, label, cls in (
    ("ptpimg", "PTPImg", PtpimgAdapter), ("imgbb", "ImgBB", ImgbbAdapter), ("lensdump", "Lensdump", LensdumpAdapter),
    ("ptscreens", "PTScreens", PtscreensAdapter), ("onlyimage", "OnlyImage", OnlyimageAdapter),
    ("dalexni", "Dalexni", DalexniAdapter), ("utppm", "utp.pm", UtppmAdapter),
    ("seedpool_cdn", "Seedpool CDN", SeedpoolCdnAdapter),
):
    register(AdapterSpec("image_host", adapter_type, label, _keyed(cls), config_fields=(API_KEY,)))
# Upload anonimi: nessuna chiave.
register(AdapterSpec("image_host", "imgbox", "Imgbox", lambda ctx: ImgboxAdapter()))
register(AdapterSpec("image_host", "pixhost", "Pixhost", lambda ctx: PixhostAdapter()))

# Notifiche: ogni istanza ha la sua riga in notification_service (cifrata), come per i plugin.
register(AdapterSpec(
    "notification", "discord", "Discord",
    lambda ctx: DiscordNotificationAdapter(ctx.config["webhook_url"], ctx.config.get("username")),
    config_fields=(
        ConfigField("webhook_url", "Webhook URL", type="secret", required=True,
                    help="Channel settings › Integrations › Webhooks › Copy webhook URL."),
        ConfigField("username", "Name shown in the channel", default="Nazgarr"),
    ),
))
register(AdapterSpec(
    "notification", "telegram", "Telegram",
    lambda ctx: TelegramNotificationAdapter(
        ctx.config["bot_token"], ctx.config["chat_id"], ctx.config.get("thread_id"),
    ),
    config_fields=(
        ConfigField("bot_token", "Bot token", type="secret", required=True,
                    help="From @BotFather. Add the bot to the chat, group or channel first."),
        ConfigField("chat_id", "Chat id", required=True,
                    help="A user, group or channel id (groups and channels start with -100)."),
        ConfigField("thread_id", "Topic id", type="number", help="Only for a group with topics."),
    ),
))

