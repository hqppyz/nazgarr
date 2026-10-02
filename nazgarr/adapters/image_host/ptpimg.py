"""PTPImg (docs/SPEC.md §9/§17) — host immagini gratuito diffuso nei
tracker privati, nessun account a pagamento richiesto, solo una api_key
personale. Shape della richiesta verificata contro Upload-Assistant
(src/uploadscreens.py, riferimento di dominio, nessun codice riusato)."""

import os

import httpx

from nazgarr.adapters.image_host.base import ImageHostAdapter, ImageHostError


class PtpimgAdapter(ImageHostAdapter):
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=30.0)

    def upload(self, image_path: str) -> str:
        try:
            with open(image_path, "rb") as f:
                response = self._client.post(
                    "https://ptpimg.me/upload.php",
                    headers={"referer": "https://ptpimg.me/index.php"},
                    data={"format": "json", "api_key": self.api_key},
                    files={"file-upload[0]": (os.path.basename(image_path), f)},
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise ImageHostError(f"Upload PTPImg fallito: {exc}") from exc

        if not data or "code" not in data[0]:
            raise ImageHostError(f"Risposta PTPImg inattesa: {data!r}")
        return f"https://ptpimg.me/{data[0]['code']}.{data[0]['ext']}"
