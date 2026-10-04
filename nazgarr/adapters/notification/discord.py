"""Notifiche su Discord, con un webhook del canale (Impostazioni del canale ›
Integrazioni › Webhook). Un messaggio con un embed: titolo, testo e colore
secondo il livello. L'URL del webhook contiene il suo token: è un segreto,
e deve essere davvero di Discord (mai un altro indirizzo)."""

import re
from datetime import UTC, datetime

import httpx

from nazgarr.adapters.notification.base import Notification, NotificationAdapter, NotificationError
from nazgarr.core import net_guard

_WEBHOOK = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+/?$")
COLORS = {"info": 0x3B82F6, "success": 0x22C55E, "warning": 0xF59E0B, "error": 0xEF4444}
TIMEOUT = 15.0


class DiscordNotificationAdapter(NotificationAdapter):
    def __init__(self, webhook_url: str, username: str | None = None, client: httpx.Client | None = None):
        url = (webhook_url or "").strip()
        if not _WEBHOOK.match(url):
            raise NotificationError("Not a Discord webhook URL (https://discord.com/api/webhooks/…)")
        self.webhook_url = url
        self.username = (username or "").strip() or "Nazgarr"
        self._client = client

    def send(self, notification: Notification) -> None:
        net_guard.check_url(self.webhook_url)
        payload = {
            "username": self.username[:80],
            "embeds": [{
                "title": notification.title[:256],
                "description": notification.body[:4096],
                "color": COLORS.get(notification.level, COLORS["info"]),
                "timestamp": datetime.now(UTC).isoformat(),
                "footer": {"text": notification.event[:2048]},
            }],
            # Mai menzioni dal testo di un evento (il nome di un torrent, per esempio).
            "allowed_mentions": {"parse": []},
        }
        client = self._client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
        try:
            response = client.post(self.webhook_url, json=payload)
        except httpx.HTTPError as exc:
            # Il messaggio di httpx può citare l'URL, che contiene il token del webhook.
            raise NotificationError(f"Discord not reachable: {type(exc).__name__}") from None
        finally:
            if self._client is None:
                client.close()
        if response.status_code >= 400:
            raise NotificationError(f"Discord answered {response.status_code}: {response.text[:200]}")
