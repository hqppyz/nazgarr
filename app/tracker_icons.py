"""Icona di un tracker per le schede delle impostazioni: la favicon del sito,
scaricata una volta dal backend e tenuta in data_dir/tracker-icons, come i
poster (app/poster_cache.py). Il browser non parla mai con il tracker.

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


def _download(client: httpx.Client, url: str) -> tuple[bytes, str] | None:
    try:
        response = client.get(url)
    except httpx.HTTPError:
        return None
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if response.status_code != 200 or content_type not in _TYPES or not response.content:
        return None
    if len(response.content) > MAX_BYTES:
        return None
    return response.content, _TYPES[content_type]


def _candidates(client: httpx.Client, base_url: str) -> list[str]:
    urls = [urljoin(base_url.rstrip("/") + "/", "favicon.ico")]
    try:
        home = client.get(base_url)
        if home.status_code == 200 and "html" in home.headers.get("content-type", ""):
            for tag in _LINK_ICON.findall(home.text[:200_000]):
                href = _HREF.search(tag)
                if href and not href.group(1).lower().endswith(".svg"):
                    urls.append(urljoin(str(home.url), href.group(1)))
    except httpx.HTTPError:
        pass
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
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)
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
    logger.info("Nessuna icona utilizzabile per il tracker %s (%s)", tracker_id, base_url)
    return None


def forget_icon(data_dir: str, tracker_id: int) -> None:
    """Dopo un cambio di URL del tracker: si riscarica alla prossima richiesta."""
    for path in (cached_icon(data_dir, tracker_id), _missing_marker(data_dir, tracker_id)):
        if path and os.path.isfile(path):
            os.remove(path)
