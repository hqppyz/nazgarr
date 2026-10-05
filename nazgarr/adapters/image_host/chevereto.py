"""Gli host "famiglia Chevereto" (PTScreens, Passtheima, imageride,
Lensdump...): la stessa piattaforma dietro host diversi, con la stessa API
(POST /api/1/upload, header X-API-Key, il file nel campo "source").
CheveretoImageHost ne fa un adapter dati l'indirizzo e la chiave, ed è
nell'SDK (nazgarr.sdk): un plugin per un altro host Chevereto è una riga.

L'annidamento della risposta cambia un poco fra un host e l'altro: il
parser prova più percorsi ragionevoli invece di assumerne uno solo che
potrebbe rompersi in silenzio."""

import os

import httpx

from nazgarr.adapters.image_host.base import ImageHostAdapter, ImageHostError


def chevereto_image_url(data: dict) -> str | None:
    """L'immagine a risoluzione piena: la descrizione la mostra ridotta
    ([img=larghezza]) e al clic apre proprio questa. La versione media solo
    se la risposta non ha l'originale."""
    candidates = [
        lambda d: d["data"]["image"]["url"],
        lambda d: d["image"]["url"],
        lambda d: d["data"]["url"],
        lambda d: d["data"]["image"]["medium"]["url"],
        lambda d: d["image"]["medium"]["url"],
        lambda d: d["data"]["medium"]["url"],
    ]
    for get_url in candidates:
        try:
            url = get_url(data)
        except (KeyError, TypeError):
            continue
        if isinstance(url, str) and url:
            return url
    return None


class CheveretoImageHost(ImageHostAdapter):
    """Upload verso un host Chevereto: endpoint è l'indirizzo completo
    dell'API (es. "https://ptscreens.com/api/1/upload"), name il nome
    dell'host negli errori."""

    def __init__(self, api_key: str, *, endpoint: str, name: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.endpoint = endpoint
        self.name = name
        self._client = client or httpx.Client(timeout=60.0)

    def upload(self, image_path: str) -> str:
        try:
            with open(image_path, "rb") as f:
                response = self._client.post(
                    self.endpoint,
                    headers={"X-API-Key": self.api_key},
                    files={"source": (os.path.basename(image_path), f)},
                )
            data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise ImageHostError(f"Upload {self.name} fallito: {exc}") from exc
        if response.status_code >= 400:
            error = data.get("error") if isinstance(data, dict) else None
            reason = error.get("message") if isinstance(error, dict) else f"HTTP {response.status_code}"
            raise ImageHostError(f"Upload {self.name} fallito: {reason}")
        url = chevereto_image_url(data)
        if not url:
            raise ImageHostError(f"Risposta {self.name} senza URL riconoscibile: {data!r}")
        return url
