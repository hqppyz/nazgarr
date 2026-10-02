"""PTScreens — host immagini famiglia Chevereto, api_key gratuita. Shape
verificata contro Upload-Assistant (src/uploadscreens.py, riferimento di
dominio, nessun codice riusato); annidamento esatto della risposta non
byte-per-byte confermato, vedi nazgarr/adapters/image_host/chevereto.py."""

import os

import httpx

from nazgarr.adapters.image_host.base import ImageHostAdapter, ImageHostError
from nazgarr.adapters.image_host.chevereto import chevereto_image_url


class PtscreensAdapter(ImageHostAdapter):
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=30.0)

    def upload(self, image_path: str) -> str:
        try:
            with open(image_path, "rb") as f:
                response = self._client.post(
                    "https://ptscreens.com/api/1/upload",
                    headers={"X-API-Key": self.api_key},
                    files={"source": (os.path.basename(image_path), f)},
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise ImageHostError(f"Upload PTScreens fallito: {exc}") from exc

        url = chevereto_image_url(data)
        if not url:
            raise ImageHostError(f"Risposta PTScreens senza URL riconoscibile: {data!r}")
        return url
