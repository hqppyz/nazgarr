"""utp.pm — host immagini famiglia Chevereto, api_key gratuita. Shape
verificata contro Upload-Assistant (src/uploadscreens.py, riferimento di
dominio, nessun codice riusato); annidamento esatto della risposta non
byte-per-byte confermato, vedi nazgarr/adapters/image_host/chevereto.py."""

import base64

import httpx

from nazgarr.adapters.image_host.base import ImageHostAdapter, ImageHostError
from nazgarr.adapters.image_host.chevereto import chevereto_image_url


class UtppmAdapter(ImageHostAdapter):
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=30.0)

    def upload(self, image_path: str) -> str:
        try:
            with open(image_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
            response = self._client.post(
                "https://utp.pm/api/1/upload",
                headers={"X-API-Key": self.api_key},
                json={"source": encoded},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise ImageHostError(f"Upload utp.pm fallito: {exc}") from exc

        url = chevereto_image_url(data)
        if not url:
            raise ImageHostError(f"Risposta utp.pm senza URL riconoscibile: {data!r}")
        return url
