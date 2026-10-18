"""MediaInfo di un file locale: l'Unique ID per il matching, il report e il
riepilogo per gli upload.

Vedi docs/SPEC.md sezione 6: l'Unique ID si confronta con quello pubblicato
dal tracker (candidate.mediainfo_match), calcolato on-demand — solo per i
candidati che hanno già superato il confronto dimensione — e tenuto solo
nella cache in memoria qui sotto (media_file.mediainfo_unique_id non si
scrive: un file cambiato lo renderebbe falso).

libmediainfo legge file che arrivano da fuori (le release della cartella
osservata, i video della libreria) ed è codice nativo: un suo crash
chiudeva l'intero processo (API, scheduler, worker degli upload), e al
riavvio il worker riprendeva lo stesso job e ricadeva; un blocco fermava
la run senza fine. Ogni lettura gira quindi in un processo figlio con un
tempo massimo (audit 2026-10-18): un crash o un blocco diventano
un'eccezione come le altre, che i chiamanti trasformano in None. Il figlio
restituisce solo testo (l'XML di MediaInfo o il report), mai oggetti
Python serializzati: un figlio compromesso non può far eseguire niente al
processo principale. Isola crash e blocchi, non è una sandbox: il figlio
gira con lo stesso utente. Costa l'avvio di un interprete, circa 60-80 ms
per lettura (misurato), e ogni file si legge una volta per tipo (la cache).
"""

import logging
import os
import re
import subprocess
import sys
import threading
from collections import OrderedDict

from pymediainfo import MediaInfo

logger = logging.getLogger(__name__)

PARSE_TIMEOUT_SECONDS = 300.0  # un disco che si risveglia, un file grande su una share lenta
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
_READ_CHUNK = 64 * 1024
_STDERR_TAIL_BYTES = 4096  # le ultime righe, per il messaggio d'errore
# Il figlio: solo pymediainfo, niente di Nazgarr. "-P": nessuna cartella di
# lavoro nel percorso degli import (un pymediainfo.py lì non si carica).
# OLDXML è quello che MediaInfo.parse usa da sé senza output (libmediainfo
# dalla 17.10; quella del pacchetto è molto più recente).
_CHILD = """
import sys
from pymediainfo import MediaInfo
path, kind = sys.argv[1], sys.argv[2]
if kind == "text":
    out = MediaInfo.parse(path, output="STRING", full=False)
else:
    out = MediaInfo.parse(path, output="OLDXML")
sys.stdout.buffer.write(out.encode("utf-8", "surrogateescape"))
"""


class MediaInfoFailed(RuntimeError):
    """La lettura nel processo figlio non è finita bene: errore, crash
    (codice d'uscita negativo: il segnale) o tempo scaduto."""


def _run_isolated(file_path: str, kind: str) -> str:
    """Il testo che MediaInfo produce per il file (kind "text": il report;
    altrimenti l'XML), letto in un processo figlio con un tempo massimo.

    L'uscita si legge a pezzi mentre arriva, mai tutta in un buffer prima
    di guardarla (subprocess.run la teneva intera in memoria, e il tetto
    scattava dopo): oltre MAX_OUTPUT_BYTES il figlio si ferma subito. Di
    stderr si tengono solo le ultime righe, per il messaggio d'errore. Un
    thread per pipe, così nessuna delle due si riempie e blocca il figlio."""
    child = subprocess.Popen(
        [sys.executable, "-P", "-c", _CHILD, file_path, kind],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    out = bytearray()
    err_tail = bytearray()
    too_big = threading.Event()

    def read_out() -> None:
        while chunk := child.stdout.read1(_READ_CHUNK):
            out.extend(chunk)
            if len(out) > MAX_OUTPUT_BYTES:
                too_big.set()
                child.kill()
                return

    def read_err() -> None:
        while chunk := child.stderr.read1(_READ_CHUNK):
            err_tail.extend(chunk)
            del err_tail[:-_STDERR_TAIL_BYTES]

    readers = [threading.Thread(target=read, daemon=True, name="mediainfo-pipe") for read in (read_out, read_err)]
    for reader in readers:
        reader.start()
    try:
        returncode = child.wait(timeout=PARSE_TIMEOUT_SECONDS)  # una scadenza totale, dall'avvio
    except subprocess.TimeoutExpired as exc:
        child.kill()
        child.wait()
        raise MediaInfoFailed(f"mediainfo did not finish within {PARSE_TIMEOUT_SECONDS:.0f}s") from exc
    finally:
        for reader in readers:
            reader.join()  # il figlio è finito: le pipe arrivano alla fine
        child.stdout.close()
        child.stderr.close()
    if too_big.is_set():
        raise MediaInfoFailed(f"mediainfo output bigger than {MAX_OUTPUT_BYTES // (1024 * 1024)} MB")
    if returncode != 0:
        lines = err_tail.decode("utf-8", "replace").strip().splitlines()
        raise MediaInfoFailed(f"mediainfo failed (exit code {returncode}): {lines[-1] if lines else 'no output'}")
    return out.decode("utf-8", "surrogateescape")

_LEADING_TOKEN_RE = re.compile(r"^(\S+)")

# Lo stesso video passa da mediainfo più volte in un upload (analisi, pack
# misti, screenshot, Unique ID): ogni lettura di un file grande su un disco
# lento costa. Risultati in cache per (dispositivo, inode, dimensione, mtime):
# un hardlink (gli stessi byte) riusa la stessa voce, un file cambiato no.
_CACHE_SIZE = 32
_cache: OrderedDict[tuple, object] = OrderedDict()
_cache_lock = threading.Lock()


def _parse(file_path: str, kind: str):
    """MediaInfo.parse in un processo figlio (_run_isolated), in cache. kind
    "object" (tracce) o "text" (il report testuale). Le eccezioni passano al
    chiamante, mai in cache."""
    st = os.stat(file_path)
    key = (kind, st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    text = _run_isolated(file_path, kind)
    # Le tracce dall'XML, come fa MediaInfo.parse senza output: solo testo dal figlio.
    result = text if kind == "text" else MediaInfo(text)
    with _cache_lock:
        _cache[key] = result
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return result


def parse(file_path: str) -> MediaInfo:
    """Le tracce di un file (MediaInfo.parse), dalla cache se il file non è cambiato."""
    return _parse(file_path, "object")


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def compute_unique_id(file_path: str) -> str | None:
    """Ritorna None se mediainfo non riesce a leggere il file o non
    espone un Unique ID (es. cartella BDMV multi-file) — mai un'eccezione
    che blocchi il motore di matching."""
    try:
        media_info = parse(file_path)
    except Exception:
        logger.exception("mediainfo fallito su %r", file_path)
        return None

    for track in media_info.general_tracks:
        raw = getattr(track, "unique_id", None)
        if raw:
            # stesso formato "<decimale> (0x...)" osservato nell'output
            # testuale del tracker: normalizziamo prendendo solo il decimale.
            match = _LEADING_TOKEN_RE.match(str(raw).strip())
            return match.group(1) if match else str(raw).strip()
    return None


def extract_full_text(file_path: str) -> str | None:
    """Report mediainfo testuale completo (lo stesso formato del comando
    CLI `mediainfo`), per la sezione Mediainfo della descrizione di upload
    (docs/SPEC.md §9). output='STRING'/full=False riproduce esattamente il
    formato usato da Upload-Assistant per lo stesso scopo (verificato
    contro la sua src/exportmi.py come riferimento di dominio, nessun
    codice riusato). None solo se mediainfo non riesce proprio a leggere il
    file — mai un'eccezione che blocchi la pipeline di upload."""
    try:
        text = _parse(file_path, "text")
    except Exception:
        logger.exception("mediainfo (testo completo) fallito su %r", file_path)
        return None
    return text or None


def _first(value) -> str | None:
    """pymediainfo mette le forme "leggibili" in liste other_*: la prima."""
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value not in (None, "") else None


def _int(value) -> int | None:
    try:
        return int(float(str(value).split(" / ")[0]))
    except (TypeError, ValueError):
        return None


def summarize(media_info: MediaInfo, file_name: str | None = None) -> dict:
    """Le informazioni che un tracker UNIT3D mostra nella sua anteprima
    MediaInfo (generale, video, audio, sottotitoli), in forma strutturata:
    servono alla scheda di anteprima e ai segnaposto del nome della release
    (nazgarr/upload/naming.py). Solo valori letti, mai calcolati a parte."""
    general = media_info.general_tracks[0] if media_info.general_tracks else None
    video = media_info.video_tracks[0] if media_info.video_tracks else None
    summary: dict = {"file_name": file_name, "general": None, "video": None, "audio": [], "subtitles": []}
    if general is not None:
        summary["general"] = {
            "format": general.format,
            "duration_ms": _int(general.duration),
            "overall_bit_rate": _int(general.overall_bit_rate),
            "file_size": _int(general.file_size),
        }
    if video is not None:
        summary["video"] = {
            "format": video.format,
            "format_profile": video.format_profile,
            "codec_id": video.codec_id,
            "bit_depth": _int(video.bit_depth),
            "width": _int(video.width),
            "height": _int(video.height),
            "scan_type": video.scan_type,
            "display_aspect_ratio": _first(video.other_display_aspect_ratio) or video.display_aspect_ratio,
            "frame_rate": video.frame_rate,
            "frame_rate_num": _int(video.frame_rate_num),
            "frame_rate_den": _int(video.frame_rate_den),
            "bit_rate": _int(video.bit_rate),
            "hdr_format": video.hdr_format,
            "hdr_format_compatibility": video.hdr_format_compatibility,
            # Il profilo Dolby Vision (es. "dvhe.07"), per {hdr_full} nei nomi.
            "hdr_format_profile": video.hdr_format_profile,
            "hdr_format_string": video.hdr_format_string,
            "transfer_characteristics": video.transfer_characteristics,
            "writing_library": video.writing_library,
            # Il disco da cui viene la traccia, se chi l'ha estratta lo scrive
            # (MakeMKV: "Blu-ray", "DVD-Video"): naming.disc_evidence.
            "original_source_medium": video.original_source_medium,
            "encoding_settings": bool(video.encoding_settings),
        }
    for track in media_info.audio_tracks:
        summary["audio"].append({
            "language": track.language,
            "title": track.title,
            "format": track.format,
            "commercial_name": track.commercial_name,
            "format_additional_features": track.format_additionalfeatures,
            "channels": _int(track.channel_s),
            "channel_layout": track.channel_layout,
            "bit_rate": _int(track.bit_rate),
            "default": track.default == "Yes",
            # Chi ha codificato l'audio (es. BAMTech, gli streaming Disney): naming.streaming_audio.
            "writing_library": track.writing_library,
        })
    for track in media_info.text_tracks:
        summary["subtitles"].append({
            "language": track.language,
            "title": track.title,
            "format": track.format,
            "forced": track.forced == "Yes",
        })
    return summary


def extract_summary(file_path: str) -> dict | None:
    """summarize() di un file locale; None se mediainfo non lo legge."""
    try:
        media_info = parse(file_path)
    except Exception:
        logger.exception("mediainfo (riepilogo) fallito su %r", file_path)
        return None
    return summarize(media_info, os.path.basename(file_path))
