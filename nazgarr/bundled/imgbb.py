"""ImgBB: host di immagini con la sua API, plugin incluso (decisione
dell'utente, 2026-10-05)."""

import base64

import httpx

from nazgarr.sdk import AdapterSpec, ConfigField, ImageHostAdapter, ImageHostError, register

PLUGIN_NAME = "nazgarr-imgbb"
DESCRIPTION = "Screenshots on ImgBB (https://imgbb.com), with your free API key."
REQUIRES_SDK = ">=1.0,<2"


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


def setup() -> None:
    register(AdapterSpec(
        "image_host", "imgbb", "ImgBB", lambda ctx: ImgbbAdapter(ctx.config["api_key"]),
        config_fields=(ConfigField("api_key", "API key", type="secret", required=True,
                                   help="Free, from https://api.imgbb.com."),),
        description="https://imgbb.com",
    ))
