"""ImgBB: host di immagini con la sua API, plugin incluso (decisione
dell'utente, 2026-10-05)."""

import base64
import threading

import httpx

from nazgarr.sdk import AdapterSpec, ConfigField, ImageHostAdapter, ImageHostError, register

PLUGIN_NAME = "nazgarr-imgbb"
DESCRIPTION = "Screenshots on ImgBB (https://imgbb.com), with your free API key."
REQUIRES_SDK = ">=1.0,<2"

_shared: httpx.Client | None = None
_shared_lock = threading.Lock()


def _shared_client() -> httpx.Client:
    """Un client per tutto il processo, come per gli host Chevereto (audit
    2026-10-18): la catena degli host si costruisce a ogni upload, e ogni
    adapter apriva il suo httpx.Client senza chiuderlo mai, con le
    connessioni lasciate al garbage collector. La chiave viaggia in ogni
    richiesta, mai nel client."""
    global _shared
    with _shared_lock:
        if _shared is None or _shared.is_closed:
            _shared = httpx.Client(timeout=60.0)
        return _shared


class ImgbbAdapter(ImageHostAdapter):
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self._client = client or _shared_client()

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
