"""Corpo di una risposta HTTP letto con un tetto, mai tutto in memoria
prima di controllarlo.

Una richiesta httpx normale (client.get) scarica e decomprime l'intera
risposta prima di restituirla: un tracker ostile, o chi si mette in mezzo
su un tracker http://, poteva mandare un .torrent da gigabyte o un gzip da
pochi KB che si espande a centinaia di MB, e il limite di 20 MB scattava
solo con tutto già in memoria nel processo unico di Nazgarr (audit
2026-10-18). Qui la risposta si legge in streaming (client.stream): il
Content-Length dichiarato si confronta prima di leggere, e i byte
decompressi si contano a ogni passo, fermandosi appena passano il tetto.
Una scadenza totale ferma anche chi manda un byte alla volta per restare
sotto il timeout di lettura.

La decompressione non la fa httpx: decomprime ogni blocco grezzo di rete
(fino a 64 KiB) in una sola chiamata senza limite d'uscita, e incatena le
codifiche ("Content-Encoding: gzip, gzip"), così 2 KB sul filo arrivavano a
GB in memoria prima del primo conteggio. Si leggono i byte grezzi
(iter_raw) e si decomprime qui un solo strato gzip o deflate, a passi di
_STEP byte al massimo; più strati o un'altra codifica sono un rifiuto.
ACCEPT_ENCODING è quello che chi chiama deve annunciare, così un server
onesto non risponde mai in una codifica che qui non si legge (httpx
annuncerebbe br o zstd appena il loro pacchetto fosse installato).
"""

import time
import zlib

import httpx

ACCEPT_ENCODING = "gzip, deflate"

_GZIP = ("gzip", "x-gzip")
_DEFLATE = ("deflate",)
# Byte decompressi al massimo per ogni chiamata a zlib.
_STEP = 1024 * 1024


class ResponseLimitExceeded(Exception):
    """Risposta che non si legge entro il tetto: più grande, più lenta della
    scadenza, o in una codifica che non si decomprime a passi limitati. Il
    messaggio completa una frase del chiamante ("The tracker sent a .torrent
    <messaggio>")."""


def _size(limit: int) -> str:
    return f"{limit // (1024 * 1024)} MB" if limit >= 1024 * 1024 else f"{limit} bytes"


def _codings(response: httpx.Response) -> list[str]:
    codings = (c.strip().lower() for c in response.headers.get_list("content-encoding", split_commas=True))
    return [c for c in codings if c and c != "identity"]


class _Inflater:
    """Un solo strato gzip o deflate, decompresso a passi di _STEP byte."""

    def __init__(self, coding: str):
        self._gzip = coding in _GZIP
        self._d = zlib.decompressobj(zlib.MAX_WBITS | 16 if self._gzip else zlib.MAX_WBITS)
        self._first = True

    def _decompress(self, data: bytes) -> bytes:
        try:
            out = self._d.decompress(data, _STEP)
        except zlib.error:
            if self._gzip or not self._first:
                raise
            # deflate senza l'intestazione zlib, come lo accetta httpx
            # (DeflateDecoder): si riprova una volta, al primo blocco.
            self._d = zlib.decompressobj(-zlib.MAX_WBITS)
            out = self._d.decompress(data, _STEP)
        if data:
            self._first = False
        return out

    def feed(self, data: bytes):
        if self._d.eof:
            # Byte dopo la fine dello stream: httpx li ignora, e zlib li
            # terrebbe tutti in unused_data, senza tetto.
            return
        yield self._decompress(data)
        while self._d.unconsumed_tail:
            yield self._d.decompress(self._d.unconsumed_tail, _STEP)

    def drain(self):
        """Quello che zlib tiene ancora da parte a fine corpo, sempre a passi
        limitati (decompress con max_length, mai flush(), che non ha tetto)."""
        while not self._d.eof:
            out = self._d.decompress(b"", _STEP)
            yield out
            if len(out) < _STEP:
                return


def read_limited(response: httpx.Response, limit: int, deadline: float | None = None) -> bytes:
    """Il corpo (decompresso) di una risposta aperta con client.stream(),
    al massimo `limit` byte. deadline: un istante di time.monotonic() oltre
    il quale si smette di leggere."""
    declared = response.headers.get("Content-Length")
    if declared is not None and declared.strip().isdigit() and int(declared) > limit:
        raise ResponseLimitExceeded(f"bigger than {_size(limit)}")
    if response.is_stream_consumed:
        # Una risposta costruita coi byte (un transport che non fa streaming,
        # come httpx.MockTransport nei test): httpx l'ha già letta e
        # decompressa, resta solo il tetto. Il transport di rete fa sempre
        # streaming e passa dal ramo sotto.
        content = response.content
        if len(content) > limit:
            raise ResponseLimitExceeded(f"bigger than {_size(limit)}")
        return content
    codings = _codings(response)
    if len(codings) > 1 or (codings and codings[0] not in _GZIP + _DEFLATE):
        raise ResponseLimitExceeded(f"with an unsupported Content-Encoding ({', '.join(codings)})")
    inflater = _Inflater(codings[0]) if codings else None
    body = bytearray()

    def take(pieces) -> None:
        for piece in pieces:
            body.extend(piece)
            if len(body) > limit:
                raise ResponseLimitExceeded(f"bigger than {_size(limit)}")

    try:
        for chunk in response.iter_raw():
            take(inflater.feed(chunk) if inflater else (chunk,))
            if deadline is not None and time.monotonic() > deadline:
                raise ResponseLimitExceeded("too slow to arrive")
        if inflater:
            take(inflater.drain())
    except zlib.error as exc:
        raise ResponseLimitExceeded(f"that cannot be decompressed ({exc})") from exc
    return bytes(body)
