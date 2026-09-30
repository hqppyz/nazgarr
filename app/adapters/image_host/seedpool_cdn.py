"""Seedpool CDN — host immagini con api_key, auth Bearer. Shape verificata
contro il codice reale e funzionante di Upload-Assistant
(src/uploadscreens.py:491-542)."""

import os

import httpx

from app.adapters.image_host.base import ImageHostAdapter, ImageHostError


class SeedpoolCdnAdapter(ImageHostAdapter):
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=30.0)

    def upload(self, image_path: str) -> str:
        try:
            with open(image_path, "rb") as f:
                response = self._client.post(
                    "https://i.seedpool.org/upload",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"files[]": (os.path.basename(image_path), f)},
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise ImageHostError(f"Upload Seedpool CDN fallito: {exc}") from exc

        files = data.get("files") or []
        if not files:
            raise ImageHostError(f"Risposta Seedpool CDN senza file caricati: {data!r}")
        entry = files[0]
        variants = entry.get("variants") or {}
        # L'originale prima di tutto (vedi chevereto_image_url).
        url = entry.get("url") or variants.get("medium") or entry.get("thumbnail_url") or variants.get("thumb")
        if not url:
            raise ImageHostError(f"Risposta Seedpool CDN senza URL riconoscibile: {data!r}")
        return url
