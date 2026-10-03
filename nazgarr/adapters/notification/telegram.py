"""Notifiche su Telegram, con un bot (creato da @BotFather) che scrive in una
chat, un gruppo o un canale: il suo token e l'id della chat (un gruppo con
gli argomenti accetta anche l'id dell'argomento). Il testo va in HTML, con
il titolo in grassetto e tutto il resto escapato."""

import html

import httpx

from nazgarr import net_guard
from nazgarr.adapters.notification.base import Notification, NotificationAdapter, NotificationError

API = "https://api.telegram.org"
ICONS = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}
TIMEOUT = 15.0
MAX_TEXT = 4096


class TelegramNotificationAdapter(NotificationAdapter):
    def __init__(self, bot_token: str, chat_id: str, thread_id: int | str | None = None,
                 client: httpx.Client | None = None):
        token = (bot_token or "").strip()
        if not token or "/" in token:
            raise NotificationError("Not a Telegram bot token")
        if not str(chat_id or "").strip():
            raise NotificationError("Missing the Telegram chat id")
        self.bot_token = token
        self.chat_id = str(chat_id).strip()
        self.thread_id = int(thread_id) if thread_id not in (None, "") else None
        self._client = client

    def send(self, notification: Notification) -> None:
        url = f"{API}/bot{self.bot_token}/sendMessage"
        net_guard.check_url(url)
        icon = ICONS.get(notification.level, ICONS["info"])
        text = f"{icon} <b>{html.escape(notification.title)}</b>\n{html.escape(notification.body)}"
        payload: dict = {
            "chat_id": self.chat_id,
            "text": text[:MAX_TEXT],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if self.thread_id is not None:
            payload["message_thread_id"] = self.thread_id
        client = self._client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
        try:
            response = client.post(url, json=payload)
        except httpx.HTTPError as exc:
            # Il messaggio di httpx può citare l'URL, che contiene il token.
            raise NotificationError(f"Telegram not reachable: {type(exc).__name__}") from None
        finally:
            if self._client is None:
                client.close()
        if response.status_code >= 400:
            # La risposta di Telegram non contiene il token, l'URL sì: mai nel messaggio.
            try:
                description = response.json().get("description") or ""
            except ValueError:
                description = ""
            raise NotificationError(f"Telegram answered {response.status_code}: {description[:200]}")
