"""Dalexni — host immagini con api_key gratuita, nessun header di auth (la
chiave va nel corpo della richiesta). Shape verificata contro il codice
reale e funzionante di Upload-Assistant (src/uploadscreens.py:171-203)."""

import base64

import httpx

from app.adapters.image_host.base import ImageHostAdapter, ImageHostError


class DalexniAdapter(ImageHostAdapter):
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=30.0)

    def upload(self, image_path: str) -> str:
        try:
            with open(image_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf8")
            response = self._client.post(
                "https://dalexni.com/1/upload", data={"key": self.api_key, "image": encoded}
            )
            data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise ImageHostError(f"Upload Dalexni fallito: {exc}") from exc

        if response.status_code != 200 or not data.get("success"):
            raise ImageHostError(f"Upload Dalexni fallito: {data!r}")

        payload = data.get("data", {})
        # L'originale prima di tutto (vedi chevereto_image_url).
        url = (
            (payload.get("image") or {}).get("url") or payload.get("url")
            or (payload.get("medium") or {}).get("url") or (payload.get("thumb") or {}).get("url")
        )
        if not url:
            raise ImageHostError(f"Risposta Dalexni senza URL riconoscibile: {data!r}")
        return url
