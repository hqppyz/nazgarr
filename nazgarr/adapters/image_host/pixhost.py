"""Pixhost — completamente anonimo, nessuna api_key (come Imgbox, ma con
una vera API HTTP documentata invece di reimplementare un form web).
Shape della richiesta verificata contro Upload-Assistant (src/uploadscreens.py,
riferimento di dominio, nessun codice riusato)."""

import os
import re

import httpx

from nazgarr.adapters.image_host.base import ImageHostAdapter, ImageHostError

_THUMB = re.compile(r"^https?://t(\d*)\.pixhost\.to/thumbs/(.+)$")


class PixhostAdapter(ImageHostAdapter):
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30.0)

    def upload(self, image_path: str) -> str:
        try:
            with open(image_path, "rb") as f:
                response = self._client.post(
                    "https://api.pixhost.to/images",
                    data={"content_type": "0", "max_th_size": "350"},
                    files={"img": (os.path.basename(image_path), f)},
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise ImageHostError(f"Upload Pixhost fallito: {exc}") from exc

        # show_url è la pagina HTML dell'immagine, non l'immagine: dentro [img]
        # non si vede. L'originale si ricava dalla miniatura (th_url), come
        # fa Upload-Assistant: t<N>.pixhost.to/thumbs/ -> img<N>.pixhost.to/images/.
        th_url = data.get("th_url") or ""
        match = _THUMB.match(th_url)
        if not match:
            raise ImageHostError(f"Risposta Pixhost senza un'immagine riconoscibile: {data!r}")
        return f"https://img{match.group(1)}.pixhost.to/images/{match.group(2)}"
