"""Corpi HTTP ostili per i test delle letture con un tetto
(nazgarr/core/http_limits.py).

Un httpx.Response costruito con content=<bytes> si legge (e si decomprime)
già nel costruttore: read_limited lo vede consumato e controlla solo la
lunghezza, così un test non passerebbe mai dalla decompressione a passi.
Qui il corpo è un generatore: httpx.MockTransport lo manda a pezzi, come la
rete, e si contano i pezzi letti.
"""

import tracemalloc
import zlib


def chunked(raw: bytes, chunk: int):
    """Un corpo mandato a pezzi da `chunk` byte: (stream, sent, total), con
    sent che cresce a ogni pezzo letto e total i pezzi del corpo intero."""
    sent: list[int] = []

    def stream():
        for i in range(0, len(raw), chunk):
            sent.append(i)
            yield raw[i:i + chunk]

    return stream, sent, -(-len(raw) // chunk)


def gzip_bomb(decoded_bytes: int, prefix: bytes = b"") -> bytes:
    """Un corpo gzip che si espande a prefix + decoded_bytes zeri (circa
    1.000 volte più piccolo sul filo)."""
    packer = zlib.compressobj(9, zlib.DEFLATED, 31)  # 31: formato gzip
    block = b"\0" * (1024 * 1024)
    parts = [packer.compress(prefix)]
    parts += [packer.compress(block) for _ in range(decoded_bytes // len(block))]
    return b"".join(parts) + packer.flush()


def peak_bytes(call) -> int:
    """Il picco di memoria allocata (tracemalloc) mentre gira call()."""
    tracemalloc.start()
    try:
        call()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
