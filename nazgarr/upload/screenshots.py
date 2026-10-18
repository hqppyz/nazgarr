"""Generazione screenshot per l'upload (docs/SPEC.md §9, Fase 6) — v1 già
la include, non rimandata. ffmpeg-python per costruire i comandi, richiede
il binario `ffmpeg` nel container (aggiunto al Dockerfile in questa stessa
fase).

Ogni comando gira con un tempo massimo (audit 2026-10-18): ffmpeg-python
aspetta il processo senza limiti, e un ffmpeg bloccato su un file
malformato teneva fermo per sempre l'unico thread dell'esecuzione, e con
lui tutta la coda degli upload. Scaduto il tempo il processo si ferma e
quello screenshot si salta; scaduto il tempo di tutti gli screenshot, si
tiene quello che c'è."""

import logging
import os
import re
import subprocess
import time

import ffmpeg

from nazgarr.library import mediainfo as mediainfo_util

logger = logging.getLogger(__name__)


class ScreenshotError(Exception):
    pass


# Un comando di ffmpeg (un fotogramma, le statistiche, un JPEG) non arriva
# mai a minuti su un file sano; tutti gli screenshot di un upload insieme
# (4 x 5 tentativi, più il tonemap) hanno un tetto a parte.
COMMAND_TIMEOUT_SECONDS = 120
TOTAL_TIMEOUT_SECONDS = 900


def _run(stream, timeout: float = COMMAND_TIMEOUT_SECONDS) -> tuple[bytes, bytes]:
    """Il comando di ffmpeg-python, ma con un tempo massimo: scaduto,
    subprocess ferma il processo. Gli errori (anche il tempo scaduto) come
    ffmpeg.Error, quelli che i chiamanti gestiscono già."""
    argv = ffmpeg.compile(stream)
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=max(timeout, 1))
    except subprocess.TimeoutExpired as exc:
        raise ffmpeg.Error("ffmpeg", exc.stdout or b"", f"ffmpeg stopped after {timeout:.0f} s".encode()) from exc
    if done.returncode != 0:
        raise ffmpeg.Error("ffmpeg", done.stdout, done.stderr)
    return done.stdout, done.stderr


# Catena di filtri ffmpeg per il tonemap HDR->SDR standard (algoritmo
# "mobius", lo stesso di Upload-Assistant) — senza, uno screenshot da
# sorgente HDR risulta lavato/scuro se interpretato come SDR a valle. Solo
# per una sorgente HDR, e con transfer, primari e matrice dichiarati ai frame
# (setparams): da un file senza i metadati di colore (molti WEB-DL) zscale
# falliva con "no path between colorspaces", e con lui ogni screenshot
# (segnalato 2026-10-09; i parametri di zscale da soli non bastano). Con i
# metadati giusti nel file, lo stesso fotogramma di prima.
def _tonemap_filter(transfer: str) -> str:
    return (
        f"setparams=color_trc={transfer}:color_primaries=bt2020:colorspace=bt2020nc,"
        "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
        "tonemap=tonemap=mobius:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
    )

# Sempre PNG a 8 bit per canale (come Upload-Assistant, format=rgb24): da una
# sorgente a 10 bit ffmpeg scriverebbe un PNG a 16 bit, che in 4K passa i
# 30 MB e gli host lo rifiutano (imgbb: 32 MB per richiesta).
_PNG_OUTPUT = {"pix_fmt": "rgb24", "compression_level": 9}
# Tetto per screenshot: sopra, lo stesso frame a piena risoluzione in JPEG di
# alta qualità (qscale 2 = la migliore usata in pratica, poi a scendere).
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
_JPEG_QUALITIES = (2, 3, 5)


def _hdr_transfer(file_path: str) -> str | None:
    """Il transfer di una sorgente HDR per zscale: "smpte2084" (PQ: HDR10,
    HDR10+, Dolby Vision) o "arib-std-b67" (HLG). None per una SDR, che non
    si tocca."""
    for track in mediainfo_util.parse(file_path).video_tracks:
        transfer = str(getattr(track, "transfer_characteristics", None) or "")
        hdr = " ".join(str(getattr(track, key, None) or "") for key in ("hdr_format", "hdr_format_compatibility"))
        if "HLG" in transfer or "HLG" in hdr:
            return "arib-std-b67"
        if "PQ" in transfer or "2084" in transfer or "HDR10" in hdr or "2086" in hdr or "Dolby Vision" in hdr:
            return "smpte2084"
    return None


def _get_duration_seconds(file_path: str) -> float:
    media_info = mediainfo_util.parse(file_path)  # già letta dall'analisi: dalla cache
    for track in media_info.video_tracks:
        if track.duration:
            return float(track.duration) / 1000.0
    raise ScreenshotError(f"Durata video non determinabile per {file_path!r}")


# Un frame quasi tutto nero o piatto (dissolvenze, cambi scena, titoli su
# nero): luminanza media o escursione sotto queste soglie, su 0-255 (il nero
# "limited range" è 16). Misurate da ffmpeg (signalstats) su una copia
# rimpicciolita del PNG appena catturato: pochi millisecondi.
MIN_AVERAGE_LUMA = 28
MIN_LUMA_RANGE = 24
# Quanti altri istanti provare per uno screenshot nero, spostandosi di questa
# frazione della distanza fra due screenshot (prima avanti, poi indietro).
RETRY_OFFSETS = (0.33, -0.33, 0.66, -0.66)
_STAT = re.compile(r"lavfi\.signalstats\.(YAVG|YMIN|YMAX)=([0-9.]+)")


def luma_stats(image_path: str, timeout: float = COMMAND_TIMEOUT_SECONDS) -> dict[str, float] | None:
    """YAVG/YMIN/YMAX di un'immagine, o None se ffmpeg non li dà."""
    try:
        _out, err = _run(
            ffmpeg.input(image_path)
            .filter("scale", 160, -1)
            # Sempre a 8 bit: da una sorgente a 10 bit il PNG è a 16 bit e
            # signalstats risponderebbe su quella scala (il nero è 4096).
            .filter("format", "gray")
            .filter("signalstats")
            .filter("metadata", mode="print")
            .output("-", format="null")
            .global_args("-hide_banner"),
            timeout,
        )
    except ffmpeg.Error:
        logger.warning("Statistiche di luminanza non disponibili per %r", image_path, exc_info=True)
        return None
    stats = {key: float(value) for key, value in _STAT.findall(err.decode("utf-8", "replace"))}
    return stats if {"YAVG", "YMIN", "YMAX"} <= stats.keys() else None


def is_blank(stats: dict[str, float] | None) -> bool:
    """Nero o piatto. Senza statistiche, nel dubbio va bene."""
    if stats is None:
        return False
    return stats["YAVG"] < MIN_AVERAGE_LUMA or stats["YMAX"] - stats["YMIN"] < MIN_LUMA_RANGE


def _ffmpeg_message(error: ffmpeg.Error) -> str:
    """Le ultime righe di ffmpeg: il motivo vero, che l'eccezione non dice."""
    lines = (error.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return " | ".join(line.strip() for line in lines[-4:]) or "no output from ffmpeg"


def _capture(video_path: str, timestamp: float, output_path: str, output_kwargs: dict,
             timeout: float = COMMAND_TIMEOUT_SECONDS) -> bool:
    try:
        _run(ffmpeg.input(video_path, ss=timestamp).output(output_path, **output_kwargs).overwrite_output()
             .global_args("-hide_banner", "-loglevel", "error"), timeout)
    except ffmpeg.Error as exc:
        logger.error("Cattura screenshot fallita a %.1fs per %r: %s", timestamp, video_path, _ffmpeg_message(exc))
        return False
    return os.path.isfile(output_path)


def _fit_size(path: str, timeout: float = COMMAND_TIMEOUT_SECONDS) -> str:
    """Il file da tenere: il PNG se sta sotto MAX_SCREENSHOT_BYTES, se no un
    JPEG dello stesso frame (stessa risoluzione) alla qualità più alta che ci
    sta; nel dubbio il JPEG più piccolo, meglio del PNG troppo grande."""
    if os.path.getsize(path) <= MAX_SCREENSHOT_BYTES:
        return path
    jpeg = os.path.splitext(path)[0] + ".jpg"
    for quality in _JPEG_QUALITIES:
        try:
            _run(ffmpeg.input(path).output(jpeg, vframes=1, qscale=quality, pix_fmt="yuvj444p").overwrite_output(),
                 timeout)
        except ffmpeg.Error:
            logger.warning("Compressione JPEG fallita per %r", path, exc_info=True)
            return path
        if os.path.getsize(jpeg) <= MAX_SCREENSHOT_BYTES:
            break
    logger.info("Screenshot %r di %d byte, tenuto in JPEG (%d byte)",
                path, os.path.getsize(path), os.path.getsize(jpeg))
    os.remove(path)
    return jpeg


def generate_screenshots(video_path: str, output_dir: str, count: int = 4, tonemap: bool = False) -> list[str]:
    """Cattura `count` frame equidistanti, escludendo il primo/ultimo 5%
    della durata (titoli/loghi/nero in apertura o coda). Un frame singolo
    che fallisce viene saltato, non blocca gli altri — solleva
    ScreenshotError solo se NESSUN frame riesce (pochi screenshot sono
    comunque meglio di un upload bloccato del tutto). tonemap=True applica
    la conversione HDR->SDR (impostazione upload_tonemap_hdr) a una
    sorgente HDR; se ffmpeg la rifiuta, gli screenshot si fanno senza.

    Un frame nero o piatto (is_blank) si riprova qualche istante più in là
    (RETRY_OFFSETS); se lo sono tutti si tiene quello con più contrasto,
    meglio di uno screenshot in meno."""
    os.makedirs(output_dir, exist_ok=True)
    duration = _get_duration_seconds(video_path)

    margin = duration * 0.05
    usable = duration - 2 * margin
    if usable <= 0:
        margin, usable = 0.0, duration

    output_kwargs = {"vframes": 1, **_PNG_OUTPUT}
    transfer = _hdr_transfer(video_path) if tonemap else None
    if transfer:
        output_kwargs["vf"] = _tonemap_filter(transfer)

    step = usable / (count + 1)
    deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS

    def left() -> float:
        return min(COMMAND_TIMEOUT_SECONDS, deadline - time.monotonic())

    paths = []
    for i in range(count):
        if left() <= 0:
            logger.warning("Screenshot di %r: tempo finito dopo %d su %d", video_path, len(paths), count)
            break
        base = margin + step * (i + 1)
        output_path = os.path.join(output_dir, f"screenshot_{i}.png")
        best: tuple[float, str] | None = None  # (escursione, file) del tentativo migliore
        for attempt, offset in enumerate((0.0, *RETRY_OFFSETS)):
            if left() <= 0:
                break  # si tiene il tentativo migliore fin qui
            timestamp = min(max(base + offset * step, margin), margin + usable)
            candidate = output_path if attempt == 0 else os.path.join(output_dir, f"screenshot_{i}_retry{attempt}.png")
            captured = _capture(video_path, timestamp, candidate, output_kwargs, left())
            if not captured and "vf" in output_kwargs and left() > 0:
                logger.warning("Tonemap HDR non riuscito per %r: screenshot senza", video_path)
                del output_kwargs["vf"]
                captured = _capture(video_path, timestamp, candidate, output_kwargs, left())
            if not captured:
                continue
            stats = luma_stats(candidate, max(left(), 1))
            if not is_blank(stats):
                best = (float("inf"), candidate)
                break
            logger.debug("Screenshot nero o piatto a %.1fs per %r, riprovo più in là", timestamp, video_path)
            spread = stats["YMAX"] - stats["YMIN"] + stats["YAVG"] if stats else 0.0
            if best is None or spread > best[0]:
                best = (spread, candidate)
        if best is None:
            continue
        if best[1] != output_path:
            os.replace(best[1], output_path)
        paths.append(_fit_size(output_path, max(left(), 1)))
        for leftover in os.listdir(output_dir):
            if leftover.startswith(f"screenshot_{i}_retry"):
                os.remove(os.path.join(output_dir, leftover))

    if not paths:
        raise ScreenshotError(f"Nessuno screenshot generato per {video_path!r}")
    return paths
