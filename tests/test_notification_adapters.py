import json

import httpx
import pytest

from nazgarr.adapters.notification.base import Notification, NotificationError
from nazgarr.adapters.notification.discord import DiscordNotificationAdapter
from nazgarr.adapters.notification.telegram import TelegramNotificationAdapter

HOOK = "https://discord.com/api/webhooks/123/abc-DEF_1"


def _client(status=204, body=None, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("nazgarr.core.net_guard.check_url", lambda url: None)


def test_discord_sends_an_embed_without_mentions():
    seen = []
    adapter = DiscordNotificationAdapter(HOOK, client=_client(seen=seen))
    adapter.send(Notification("upload.finished", "Upload done: @everyone", "ITT: upload done", "success"))

    request = seen[0]
    assert str(request.url) == HOOK
    payload = json.loads(request.content)
    embed = payload["embeds"][0]
    assert (embed["title"], embed["description"], embed["color"]) == (
        "Upload done: @everyone", "ITT: upload done", 0x22C55E)
    assert payload["allowed_mentions"] == {"parse": []} and payload["username"] == "Nazgarr"


def test_discord_only_accepts_discord_webhooks_and_reports_errors():
    for url in ("https://evil.example/api/webhooks/1/x", "http://discord.com/api/webhooks/1/x", "", "not a url"):
        with pytest.raises(NotificationError):
            DiscordNotificationAdapter(url)
    DiscordNotificationAdapter("https://canary.discordapp.com/api/webhooks/9/tok")
    with pytest.raises(NotificationError, match="429"):
        DiscordNotificationAdapter(HOOK, client=_client(429, {"retry_after": 1})).send(Notification("test", "t", "b"))


def test_telegram_escapes_the_text_and_uses_the_topic():
    seen = []
    adapter = TelegramNotificationAdapter("123:ABC", "-100777", "42", client=_client(200, {"ok": True}, seen))
    adapter.send(Notification("seed_job.finished", "Reseed <failed>", "Movie & co.", "error"))

    request = seen[0]
    assert str(request.url) == "https://api.telegram.org/bot123:ABC/sendMessage"
    payload = json.loads(request.content)
    assert payload["text"] == "❌ <b>Reseed &lt;failed&gt;</b>\nMovie &amp; co."
    assert (payload["chat_id"], payload["message_thread_id"], payload["parse_mode"]) == ("-100777", 42, "HTML")


def test_telegram_errors_never_carry_the_token():
    answer = {"ok": False, "description": "chat not found"}
    adapter = TelegramNotificationAdapter("123:SECRET", "1", client=_client(400, answer))
    with pytest.raises(NotificationError) as error:
        adapter.send(Notification("test", "t", "b"))
    assert "chat not found" in str(error.value) and "SECRET" not in str(error.value)
    def unreachable(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    no_network = httpx.Client(transport=httpx.MockTransport(unreachable))
    offline = TelegramNotificationAdapter("123:SECRET", "1", client=no_network)
    with pytest.raises(NotificationError) as error:
        offline.send(Notification("test", "t", "b"))
    assert "SECRET" not in str(error.value)
    with pytest.raises(NotificationError):
        TelegramNotificationAdapter("", "1")
    with pytest.raises(NotificationError):
        TelegramNotificationAdapter("1:a", " ")


def test_both_are_built_in_notification_services():
    from nazgarr.plugins import REGISTRY

    discord, telegram = REGISTRY.get("notification", "discord"), REGISTRY.get("notification", "telegram")
    assert [f.key for f in discord.required_fields] == ["webhook_url"]
    assert [f.key for f in telegram.required_fields] == ["bot_token", "chat_id"]
    assert {f.key for f in discord.config_fields if f.type == "secret"} == {"webhook_url"}
