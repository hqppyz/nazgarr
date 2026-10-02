"""Verifica byte-esatta di un file locale contro gli hash dei piece
dichiarati in un .torrent (BEP3).

Perché: l'Unique ID mediainfo (usato in nazgarr/matching.py) confronta un
riassunto del container e può non discriminare release con stesso video
ma audio diverso (vedi docs/SPEC.md sezione 6). Gli hash piece del
.torrent sono invece la stessa prova che userà il client per il recheck
reale — byte-esatta, non euristica. Tecnica adattata da smartmediareseed
(vedi docs/SPEC.md sezione 0).

Le piece a cavallo tra due file adiacenti nel torrent (comune nei season
pack) non sono verificabili leggendo solo questo file: contate a parte in
`boundary`, mai giudicate un mismatch.

NON sostituisce mai il recheck reale lato client (docs/SPEC.md sezione 8,
`nazgarr/executor.py` con force_recheck=True sempre): è solo un segnale di
confidence in più per il motore di matching.

Porting diretto da ratio-guardian/app/torrent_pieces.py."""

import hashlib
from dataclasses import dataclass


@dataclass
class PieceVerifyResult:
    ok: int
    mismatches: int
    boundary: int

    @property
    def checked(self) -> int:
        return self.ok + self.mismatches

    @property
    def clean(self) -> bool:
        """Nessun mismatch reale, e almeno un dato utile è stato ottenuto
        (una piece verificata o di boundary) — mai True su un risultato
        vuoto (es. file illeggibile, vedi verify_file_pieces)."""
        return self.mismatches == 0 and (self.ok > 0 or self.boundary > 0)


def verify_file_pieces(
    local_path: str,
    piece_length: int,
    pieces: list[bytes],
    total_length: int,
    file_offset: int,
    file_length: int,
    max_pieces: int | None = None,
) -> PieceVerifyResult:
    """file_offset/file_length: posizione del file nel flusso concatenato
    virtuale del torrent (vedi nazgarr/torrent_file.py::TorrentFileEntry).
    Legge dal disco solo le porzioni corrispondenti a piece interamente
    contenute nel range di questo file, mai l'intero file se non serve.
    Degrada a un risultato vuoto (mai un'eccezione) su qualunque problema
    di I/O o di dati malformati — il chiamante tratta un risultato vuoto
    (clean=False) come "nessuna prova ottenuta", non come un mismatch.

    max_pieces: verifica al più quel numero di piece, distribuiti lungo il
    file (primo e ultimo compresi) invece di tutti. Il matching lo usa
    sempre: leggere per intero un remux da decine di GB (o ogni episodio di
    un pack) costava minuti per candidato, mentre size esatta + un campione
    di hash coincidenti rende un falso positivo praticamente impossibile —
    e il recheck completo lo fa comunque il client prima di seedare."""
    if file_length <= 0:
        return PieceVerifyResult(ok=0, mismatches=0, boundary=0)

    file_end = file_offset + file_length
    first_idx = file_offset // piece_length
    last_idx = (file_end - 1) // piece_length

    inner: list[int] = []
    boundary = 0
    for idx in range(first_idx, last_idx + 1):
        piece_start = idx * piece_length
        piece_end = min(piece_start + piece_length, total_length)
        if piece_start < file_offset or piece_end > file_end:
            # Condivisa con un file adiacente nel torrent: non
            # verificabile isolando solo questo file.
            boundary += 1
        else:
            inner.append(idx)
    if max_pieces is not None and len(inner) > max_pieces:
        if max_pieces <= 1:
            inner = inner[:max_pieces]
        else:
            step = (len(inner) - 1) / (max_pieces - 1)
            inner = sorted({inner[round(i * step)] for i in range(max_pieces)})

    ok = mismatches = 0
    try:
        with open(local_path, "rb") as fh:
            for idx in inner:
                piece_start = idx * piece_length
                piece_end = min(piece_start + piece_length, total_length)
                fh.seek(piece_start - file_offset)
                chunk = fh.read(piece_end - piece_start)
                if hashlib.sha1(chunk).digest() == pieces[idx]:
                    ok += 1
                else:
                    mismatches += 1
    except (OSError, IndexError):
        return PieceVerifyResult(ok=0, mismatches=0, boundary=0)

    return PieceVerifyResult(ok=ok, mismatches=mismatches, boundary=boundary)
