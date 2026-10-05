"""Gli host di immagini inclusi (decisione dell'utente, 2026-10-05): solo
host con una API key, niente upload anonimi. PTScreens, Passtheima e
imageride sono Chevereto; ImgBB ha la sua API. Lensdump, a pagamento, è un
plugin d'esempio da installare (examples/nazgarr-lensdump). Altri host:
un plugin, come questo."""

import base64

import httpx

from nazgarr.sdk import (
    AdapterSpec,
    CheveretoImageHost,
    ConfigField,
    ImageHostAdapter,
    ImageHostError,
    register,
)

PLUGIN_NAME = "nazgarr-image-hosts"
REQUIRES_SDK = ">=1.2,<2"


def _api_key(url: str) -> ConfigField:
    return ConfigField("api_key", "API key", type="secret", required=True, help=f"From your account at {url}.")


# (adapter_type, nome, endpoint dell'API, dove si prende la chiave)
CHEVERETO_HOSTS = (
    ("ptscreens", "PTScreens", "https://ptscreens.com/api/1/upload", "https://ptscreens.com/settings/api"),
    ("passtheima", "Passtheima", "https://passtheima.ge/api/1/upload", "https://passtheima.ge/settings/api"),
    ("imageride", "imageride", "https://www.imageride.net/api/1/upload", "https://www.imageride.net/settings/api"),
)


class ImgbbAdapter(ImageHostAdapter):
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=60.0)

    def upload(self, image_path: str) -> str:
        try:
            with open(image_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
            response = self._client.post(
                "https://api.imgbb.com/1/upload", data={"key": self.api_key, "image": encoded}
            )
            data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise ImageHostError(f"Upload ImgBB fallito: {exc}") from exc
        if response.status_code != 200 or not data.get("success"):
            reason = (data.get("error") or {}).get("message", "risposta non riuscita")
            raise ImageHostError(f"Upload ImgBB fallito: {reason}")
        return data["data"]["image"]["url"]


def _chevereto(name: str, endpoint: str):
    return lambda ctx: CheveretoImageHost(ctx.config["api_key"], endpoint=endpoint, name=name)


def setup() -> None:
    for adapter_type, name, endpoint, keys_url in CHEVERETO_HOSTS:
        register(AdapterSpec("image_host", adapter_type, name, _chevereto(name, endpoint),
                             config_fields=(_api_key(keys_url),), description=endpoint.split("/api/")[0]))
    register(AdapterSpec("image_host", "imgbb", "ImgBB", lambda ctx: ImgbbAdapter(ctx.config["api_key"]),
                         config_fields=(_api_key("https://api.imgbb.com"),), description="https://imgbb.com"))
