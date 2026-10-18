"""Cache locale dei poster TMDB (docs/SPEC.md sezione 4/6).

Scaricato una sola volta per tmdb_id, mai in DB (solo il path relativo
TMDB, media_item.tmdb_poster_path) — l'immagine vive sul filesystem sotto
data_dir/posters/{content_type}-{tmdb_id}.jpg: film e serie hanno
numerazioni separate su TMDB, col solo tmdb_id il film 1399 e la serie
1399 si sovrascrivevano a vicenda.

Larghezza w342 (audit 2026-10-18): nessuna vista mostra un poster più largo
di circa 200 px CSS (la griglia della libreria, le schede), quindi w342 basta
anche a 2x; w500 pesava circa il doppio in byte e in pixel da decodificare.
I file già scaricati a w500 restano come sono.
"""

import contextlib
import os
import tempfile
import time

import httpx

from nazgarr.core import http_limits

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w342"
# Un poster w342 è qualche decina di KB: il tetto ferma solo una risposta
# che non è un poster, letta in streaming (nazgarr/core/http_limits.py).
MAX_POSTER_BYTES = 10 * 1024 * 1024
DOWNLOAD_DEADLINE_SECONDS = 60.0


def poster_file(posters_dir: str, content_type: str, tmdb_id: int) -> str:
    return os.path.join(posters_dir, f"{'tv' if content_type == 'tv' else 'movie'}-{tmdb_id}.jpg")


def download_poster(
    posters_dir: str, content_type: str, tmdb_id: int, poster_path: str, client: httpx.Client | None = None
) -> str:
    """Idempotente: se il file esiste già non lo riscarica. Ritorna il path
    locale. Il file si scrive accanto e si rinomina solo a download finito:
    un download interrotto lasciava un poster troncato, mai più riscaricato."""
    os.makedirs(posters_dir, exist_ok=True)
    local_path = poster_file(posters_dir, content_type, tmdb_id)
    if os.path.exists(local_path):
        return local_path

    owns_client = client is None
    client = client or httpx.Client(timeout=10.0)
    partial = None
    try:
        with client.stream("GET", f"{TMDB_IMAGE_BASE}{poster_path}",
                           headers={"Accept-Encoding": http_limits.ACCEPT_ENCODING}) as response:
            response.raise_for_status()
            try:
                content = http_limits.read_limited(response, MAX_POSTER_BYTES,
                                                   time.monotonic() + DOWNLOAD_DEADLINE_SECONDS)
            except http_limits.ResponseLimitExceeded as exc:
                # Un errore HTTP come gli altri per chi chiama (502 dall'API dei poster).
                raise httpx.DecodingError(f"TMDB sent a poster {exc}", request=response.request) from exc
        # Un nome solo suo: due richieste dello stesso poster non si scrivono addosso.
        fd, partial = tempfile.mkstemp(dir=posters_dir, prefix=".poster-", suffix=".part")
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.chmod(partial, 0o644)  # come un file scritto con open(), non 0600 di mkstemp
        os.replace(partial, local_path)
    finally:
        if partial is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(partial)
        if owns_client:
            client.close()
    return local_path
