"""Icona di un tracker per le schede delle impostazioni: la favicon del sito,
scaricata una volta dal backend e tenuta in data_dir/tracker-icons, come i
poster (nazgarr/poster_cache.py). Il browser non parla mai con il tracker.

Prima /favicon.ico, poi il <link rel="icon"> della home. Solo immagini
raster (niente SVG: servita dalla nostra origine potrebbe eseguire script se
aperta direttamente), al massimo MAX_BYTES. Se non se ne trova una, un
segnaposto evita di riprovare prima di RETRY_SECONDS.
"""

import logging
import os
import re
import time
from urllib.parse import urljoin

import httpx

from nazgarr import net_guard

logger = logging.getLogger(__name__)

MAX_BYTES = 256 * 1024
RETRY_SECONDS = 7 * 24 * 3600
TIMEOUT_SECONDS = 5.0
_TYPES = {
    "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico", "image/png": ".png", "image/jpeg": ".jpg",
    "image/gif": ".gif", "image/webp": ".webp",
}
_LINK_ICON = re.compile(r"<link[^>]+rel=[\"'][^\"']*icon[^\"']*[\"'][^>]*>", re.IGNORECASE)
_HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)


def _icon_dir(data_dir: str) -> str:
    path = os.path.join(data_dir, "tracker-icons")
    os.makedirs(path, exist_ok=True)
    return path


def cached_icon(data_dir: str, tracker_id: int) -> str | None:
    folder = _icon_dir(data_dir)
    for ext in set(_TYPES.values()):
        path = os.path.join(folder, f"{tracker_id}{ext}")
        if os.path.isfile(path):
            return path
    return None


def _missing_marker(data_dir: str, tracker_id: int) -> str:
    return os.path.join(_icon_dir(data_dir), f"{tracker_id}.missing")


MAX_REDIRECTS = 3


def _get(client: httpx.Client, url: str, limit: int) -> tuple[httpx.Response, bytes] | None:
    """Una GET che segue al massimo MAX_REDIRECTS redirect, controllando ogni
    destinazione (nazgarr/net_guard.py: mai i metadati del cloud), e smette di
    leggere oltre limit byte invece di caricare tutto in memoria."""
    for _ in range(MAX_REDIRECTS + 1):
        try:
            net_guard.check_url(url)
            with client.stream("GET", url) as response:
                if response.is_redirect and response.headers.get("location"):
                    url = urljoin(str(response.url), response.headers["location"])
                    continue
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > limit:
                        return None
                return response, body
        except (httpx.HTTPError, net_guard.ForbiddenDestination):
            return None
    return None


def _download(client: httpx.Client, url: str) -> tuple[bytes, str] | None:
    got = _get(client, url, MAX_BYTES)
    if got is None:
        return None
    response, body = got
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if response.status_code != 200 or content_type not in _TYPES or not body:
        return None
    return body, _TYPES[content_type]


def _candidates(client: httpx.Client, base_url: str) -> list[str]:
    urls = [urljoin(base_url.rstrip("/") + "/", "favicon.ico")]
    got = _get(client, base_url, 200_000 + 1)  # basta l'inizio della pagina per i <link>
    if got is None:
        return urls
    home, body = got
    if home.status_code == 200 and "html" in home.headers.get("content-type", ""):
        text = body[:200_000].decode("utf-8", "replace")
        for tag in _LINK_ICON.findall(text):
            href = _HREF.search(tag)
            if href and not href.group(1).lower().endswith(".svg"):
                url = urljoin(str(home.url), href.group(1))
                if url.lower().startswith(("http://", "https://")):
                    urls.append(url)
    return urls


def fetch_icon(data_dir: str, tracker_id: int, base_url: str, client: httpx.Client | None = None) -> str | None:
    """Percorso dell'icona in cache, scaricandola se serve; None se il
    tracker non ne ha una utilizzabile (o non risponde)."""
    cached = cached_icon(data_dir, tracker_id)
    if cached:
        return cached
    marker = _missing_marker(data_dir, tracker_id)
    if os.path.isfile(marker) and time.time() - os.path.getmtime(marker) < RETRY_SECONDS:
        return None
    owns = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
    try:
        for url in _candidates(client, base_url):
            found = _download(client, url)
            if found:
                content, ext = found
                path = os.path.join(_icon_dir(data_dir), f"{tracker_id}{ext}")
                with open(path, "wb") as f:
                    f.write(content)
                return path
    finally:
        if owns:
            client.close()
    with open(marker, "w") as f:
        f.write(base_url)
    logger.debug("Nessuna icona utilizzabile per il tracker %s (%s)", tracker_id, base_url)
    return None


def forget_icon(data_dir: str, tracker_id: int) -> None:
    """Dopo un cambio di URL del tracker: si riscarica alla prossima richiesta."""
    for path in (cached_icon(data_dir, tracker_id), _missing_marker(data_dir, tracker_id)):
        if path and os.path.isfile(path):
            os.remove(path)
