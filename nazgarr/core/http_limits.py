"""Corpo di una risposta HTTP letto con un tetto, mai tutto in memoria
prima di controllarlo.

Una richiesta httpx normale (client.get) scarica e decomprime l'intera
risposta prima di restituirla: un tracker ostile, o chi si mette in mezzo
su un tracker http://, poteva mandare un .torrent da gigabyte o un gzip da
pochi KB che si espande a centinaia di MB, e il limite di 20 MB scattava
solo con tutto già in memoria nel processo unico di Nazgarr (audit
2026-10-18). Qui la risposta si legge in streaming (client.stream): il
Content-Length dichiarato si confronta prima di leggere, e i byte già
decompressi si contano a ogni blocco, fermandosi appena passano il tetto.
Una scadenza totale ferma anche chi manda un byte alla volta per restare
sotto il timeout di lettura.

Un blocco grezzo di rete (64 KiB) si decomprime per intero prima di
contarlo: il picco resta comunque di decine di MB, non dell'intero corpo.
"""

import time

import httpx


class ResponseLimitExceeded(Exception):
    """Risposta più grande del tetto, o più lenta della scadenza."""


def _size(limit: int) -> str:
    return f"{limit // (1024 * 1024)} MB" if limit >= 1024 * 1024 else f"{limit} bytes"


def read_limited(response: httpx.Response, limit: int, deadline: float | None = None) -> bytes:
    """Il corpo (decompresso) di una risposta aperta con client.stream(),
    al massimo `limit` byte. deadline: un istante di time.monotonic() oltre
    il quale si smette di leggere."""
    declared = response.headers.get("Content-Length")
    if declared is not None and declared.strip().isdigit() and int(declared) > limit:
        raise ResponseLimitExceeded(f"bigger than {_size(limit)}")
    body = bytearray()
    for chunk in response.iter_bytes():
        body += chunk
        if len(body) > limit:
            raise ResponseLimitExceeded(f"bigger than {_size(limit)}")
        if deadline is not None and time.monotonic() > deadline:
            raise ResponseLimitExceeded("too slow to arrive")
    return bytes(body)
