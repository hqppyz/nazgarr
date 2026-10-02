"""ImgBB (docs/SPEC.md §9/§17) — host immagini generico con api_key
gratuita. Shape della richiesta verificata contro Upload-Assistant
(src/uploadscreens.py, riferimento di dominio, nessun codice riusato)."""

import base64

import httpx

from nazgarr.adapters.image_host.base import ImageHostAdapter, ImageHostError


class ImgbbAdapter(ImageHostAdapter):
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=30.0)

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
            reason = data.get("error", {}).get("message", "risposta non riuscita")
            raise ImageHostError(f"Upload ImgBB fallito: {reason}")
        return data["data"]["image"]["url"]
