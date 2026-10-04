"""ntfy notifications for Nazgarr: an example plugin (docs/SDK.md).

Install it by adding its package to NAZGARR_PLUGINS (or plugins.txt in the
data folder), for example straight from a git checkout:

    NAZGARR_PLUGINS="git+https://github.com/you/nazgarr-ntfy"

then configure it in Settings > Plugins: the server, the topic and, for a
protected topic, an access token.
"""

import httpx

import nazgarr.sdk as sdk

# The SDK versions this plugin works with (a PEP 440 specifier).
REQUIRES_SDK = ">=1.0,<2"

PRIORITY = {"info": "3", "success": "3", "warning": "4", "error": "5"}
TAGS = {"info": "information_source", "success": "white_check_mark", "warning": "warning", "error": "rotating_light"}


class NtfyNotifier(sdk.NotificationAdapter):
    def __init__(self, server: str, topic: str, token: str | None = None, client: httpx.Client | None = None):
        self.url = f"{server.rstrip('/')}/{topic}"
        self.token = token
        self.client = client or httpx.Client(timeout=10.0)

    def send(self, notification: sdk.Notification) -> None:
        headers = {
            "Title": notification.title,
            "Priority": PRIORITY.get(notification.level, "3"),
            "Tags": TAGS.get(notification.level, ""),
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self.client.post(self.url, content=notification.body.encode(), headers=headers)
        except httpx.HTTPError as exc:
            raise sdk.NotificationError(str(exc)) from exc
        if response.status_code >= 300:
            raise sdk.NotificationError(f"ntfy answered {response.status_code}: {response.text[:200]}")


def setup() -> None:
    """Called by Nazgarr at startup: register the adapters of this plugin."""
    sdk.register(sdk.AdapterSpec(
        kind="notification",
        adapter_type="ntfy",
        label="ntfy",
        description="Push notifications through an ntfy server",
        config_fields=(
            sdk.ConfigField("server", "Server", type="url", default="https://ntfy.sh"),
            sdk.ConfigField("topic", "Topic", required=True, help="Anyone who knows a public topic can read it."),
            sdk.ConfigField("token", "Access token", type="secret", help="Only for a protected topic."),
        ),
        build=lambda ctx: NtfyNotifier(ctx.config["server"] or "https://ntfy.sh", ctx.config["topic"],
                                       ctx.config.get("token")),
    ))
