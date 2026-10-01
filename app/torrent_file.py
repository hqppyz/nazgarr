"""Parser bencode minimale per un .torrent (BEP3).

Due usi:
1. Estrarre la cartella radice REALE di un torrent multi-file dal suo
   download_link — l'unica fonte davvero affidabile quando il tracker non
   riporta esplicitamente una cartella (vedi extract_root_folder/fetch_root_folder).
   Perché serve: `attributes.name` di UNIT3D è un titolo "leggibile" pensato
   per la UI (spazi), non necessariamente il vero nome di release scritto
   nel file .torrent (punti, es. "Stranger.Things.S05...."). Usarlo come
   fallback per la cartella produce un path che il client torrent NON
   riconosce — lui calcola sempre `save_path/info.name/...` dal .torrent
   reale, mai da quello che gli passiamo noi — causando un mismatch che fa
   fallire il recheck (osservato in ratio-guardian: risalita fino al 99% e
   poi fallimento). Il bencode del .torrent (BEP3) riporta invece sempre il
   nome vero in `info.name` per un torrent multi-file, mai un titolo cosmetico.
2. Estrarre piece_length/pieces/file_list con offset byte (parse_torrent_info)
   e calcolare l'info_hash (compute_info_hash) — fondamenta per la verifica
   piece-hash in app/torrent_pieces.py.

Porting diretto da ratio-guardian/app/torrent_file.py (già verificato,
nessuna logica riscoperta qui)."""

import hashlib
from typing import NamedTuple

import httpx


class TorrentMetainfoError(Exception):
    """Mai fatale per l'esecuzione: il chiamante deve trattarlo come
    "cartella non determinabile", lasciando che la validazione esplicita
    già esistente (es. app/executor.py) segnali l'assenza di una cartella
    — mai indovinare un nome sbagliato."""


# Un .torrent arriva da un tracker, cioè da chiunque ci abbia caricato
# qualcosa: niente nidificazione infinita (un RecursionError fermava la run),
# chiavi dei dizionari sempre stringhe di byte, lunghezze che non escono dal
# file.
MAX_DEPTH = 64


def _decode(data: bytes, i: int, depth: int = 0):
    if depth > MAX_DEPTH:
        raise TorrentMetainfoError("Formato bencode non valido: nidificazione troppo profonda")
    c = data[i:i + 1]
    if c == b"i":
        end = data.index(b"e", i)
        return int(data[i + 1:end]), end + 1
    if c == b"l":
        i += 1
        result = []
        while data[i:i + 1] != b"e":
            item, i = _decode(data, i, depth + 1)
            result.append(item)
        return result, i + 1
    if c == b"d":
        i += 1
        result = {}
        while data[i:i + 1] != b"e":
            key, i = _decode(data, i, depth + 1)
            if not isinstance(key, bytes):
                raise TorrentMetainfoError(f"Formato bencode non valido: chiave non stringa a offset {i}")
            value, i = _decode(data, i, depth + 1)
            result[key] = value
        return result, i + 1
    if c.isdigit():
        colon = data.index(b":", i)
        length = int(data[i:colon])
        start = colon + 1
        if length < 0 or start + length > len(data):
            raise TorrentMetainfoError(f"Formato bencode non valido: stringa oltre la fine a offset {i}")
        return data[start:start + length], start + length
    raise TorrentMetainfoError(f"Formato bencode non valido a offset {i}")


def decode(data: bytes):
    try:
        value, _ = _decode(data, 0)
    except (IndexError, ValueError, RecursionError, TypeError) as exc:
        raise TorrentMetainfoError("Impossibile decodificare il .torrent (bencode malformato)") from exc
    return value


def extract_root_folder(torrent_bytes: bytes) -> str | None:
    """None per un torrent a file singolo (info.name è il nome del file,
    non una cartella)."""
    metainfo = decode(torrent_bytes)
    if not isinstance(metainfo, dict) or b"info" not in metainfo:
        raise TorrentMetainfoError("Struttura .torrent inattesa: manca il dizionario 'info'")
    info = metainfo[b"info"]
    if b"files" not in info:
        return None
    name = info.get(b"name")
    if name is None:
        raise TorrentMetainfoError("Struttura .torrent inattesa: 'info.name' mancante per un torrent multi-file")
    try:
        return name.decode("utf-8")
    except UnicodeDecodeError:
        return name.decode("latin-1")


def fetch_root_folder(client: httpx.Client, download_link: str) -> str | None:
    """Scarica il .torrent da download_link e ne estrae la cartella radice
    reale (None per un torrent a file singolo). Solleva TorrentMetainfoError
    su qualunque problema (rete, formato) — il chiamante deve trattarlo
    come "cartella non determinabile", mai come errore fatale."""
    try:
        response = client.get(download_link)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TorrentMetainfoError(f"Download del .torrent fallito: {exc}") from exc
    return extract_root_folder(response.content)


def _decode_str(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("latin-1")


class TorrentFileEntry(NamedTuple):
    """Un file dichiarato nel .torrent, con offset assoluto nel flusso
    concatenato virtuale usato da BitTorrent v1 per indicizzare le piece
    (comportamento standard per i torrent multi-file: i file sono
    concatenati nell'ordine dichiarato, le piece tagliano quel flusso senza
    riguardo ai confini tra un file e l'altro)."""

    path: str  # path relativo (separatore "/"), o il nome del file per un torrent a file singolo
    length: int
    offset: int


class TorrentInfo(NamedTuple):
    name: str
    piece_length: int
    pieces: list[bytes]  # un hash SHA-1 (20 byte) per piece, nell'ordine del torrent
    files: list[TorrentFileEntry]
    is_multi_file: bool
    total_length: int


def _safe_component(value: str, what: str) -> str:
    """Un nome o una parte di percorso di un .torrent (che arriva da un
    tracker, cioè da chiunque ci abbia caricato qualcosa): mai vuoto, "." o
    "..", mai con separatori o byte nulli. Senza questo controllo un
    percorso come ["..", "..", "etc", "x"] o "/mnt/disk1/privato" usciva dalla
    cartella in cui Nazgarr cerca e collega i file."""
    if value in ("", ".", "..") or any(ch in value for ch in ("/", "\\", "\x00")):
        raise TorrentMetainfoError(f"Struttura .torrent non sicura: {what} {value!r} non valido")
    return value


def parse_torrent_info(torrent_bytes: bytes) -> TorrentInfo:
    """Estrae da un .torrent tutto ciò che serve per la verifica piece-hash
    (app/torrent_pieces.py::verify_file_pieces): nome, piece_length, l'elenco
    degli hash piece e la lista file con offset. Solleva TorrentMetainfoError
    per qualunque struttura inattesa — mai un dato parziale/indovinato."""
    metainfo = decode(torrent_bytes)
    if not isinstance(metainfo, dict) or b"info" not in metainfo:
        raise TorrentMetainfoError("Struttura .torrent inattesa: manca il dizionario 'info'")
    info = metainfo[b"info"]
    if not isinstance(info, dict):
        raise TorrentMetainfoError("Struttura .torrent inattesa: 'info' non è un dizionario")

    name_raw = info.get(b"name")
    if name_raw is None:
        raise TorrentMetainfoError("Struttura .torrent inattesa: 'info.name' mancante")
    name = _safe_component(_decode_str(name_raw), "nome")

    piece_length = info.get(b"piece length")
    pieces_blob = info.get(b"pieces")
    if not isinstance(piece_length, int) or piece_length <= 0:
        raise TorrentMetainfoError("Struttura .torrent inattesa: 'info.piece length' mancante o non valida")
    if not isinstance(pieces_blob, bytes) or len(pieces_blob) % 20 != 0:
        raise TorrentMetainfoError("Struttura .torrent inattesa: 'info.pieces' mancante o non un multiplo di 20 byte")
    pieces = [pieces_blob[i : i + 20] for i in range(0, len(pieces_blob), 20)]

    files: list[TorrentFileEntry] = []
    if b"files" in info:
        offset = 0
        for entry in info[b"files"]:
            if not isinstance(entry, dict):
                raise TorrentMetainfoError("Struttura .torrent inattesa: voce 'files' non è un dizionario")
            length = entry.get(b"length")
            path_parts = entry.get(b"path")
            if not isinstance(length, int) or not path_parts:
                raise TorrentMetainfoError("Struttura .torrent inattesa: voce 'files' malformata")
            rel_path = "/".join(_safe_component(_decode_str(part), "percorso") for part in path_parts)
            files.append(TorrentFileEntry(path=rel_path, length=length, offset=offset))
            offset += length
        is_multi_file = True
        total_length = offset
    else:
        length = info.get(b"length")
        if not isinstance(length, int):
            raise TorrentMetainfoError("Struttura .torrent inattesa: 'info.length' mancante per un file singolo")
        files = [TorrentFileEntry(path=name, length=length, offset=0)]
        is_multi_file = False
        total_length = length

    return TorrentInfo(
        name=name,
        piece_length=piece_length,
        pieces=pieces,
        files=files,
        is_multi_file=is_multi_file,
        total_length=total_length,
    )


def compute_info_hash(torrent_bytes: bytes) -> str:
    """SHA-1 esadecimale del dizionario 'info' del .torrent, calcolato
    sullo span di byte grezzo così com'è nel file — MAI ricodificando il
    dizionario decodificato. Ricodificare rischierebbe di normalizzare
    l'ordine delle chiavi o l'encoding e produrre un hash diverso da quello
    che client/tracker calcolano dal file originale."""
    start, end = _find_info_span(torrent_bytes)
    return hashlib.sha1(torrent_bytes[start:end]).hexdigest()


def _find_info_span(data: bytes) -> tuple[int, int]:
    if data[0:1] != b"d":
        raise TorrentMetainfoError("Il .torrent non è un dizionario bencode di primo livello")
    i = 1
    while data[i : i + 1] != b"e":
        key, i = _decode(data, i)
        value_start = i
        _, i = _decode(data, i)
        if key == b"info":
            return value_start, i
    raise TorrentMetainfoError("Struttura .torrent inattesa: manca il dizionario 'info'")
