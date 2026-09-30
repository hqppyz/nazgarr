"""Generazione screenshot per l'upload (docs/SPEC.md §9, Fase 6) — v1 già
la include, non rimandata. ffmpeg-python, richiede il binario `ffmpeg` nel
container (aggiunto al Dockerfile in questa stessa fase)."""

import logging
import os
import re

import ffmpeg
from pymediainfo import MediaInfo

logger = logging.getLogger(__name__)


class ScreenshotError(Exception):
    pass


# Catena di filtri ffmpeg per il tonemap HDR->SDR standard (algoritmo
# "mobius", lo stesso di Upload-Assistant) — senza, uno screenshot da
# sorgente HDR risulta lavato/scuro se interpretato come SDR a valle.
_HDR_TONEMAP_FILTER = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=mobius:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)


def _get_duration_seconds(file_path: str) -> float:
    media_info = MediaInfo.parse(file_path)
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


def luma_stats(image_path: str) -> dict[str, float] | None:
    """YAVG/YMIN/YMAX di un'immagine, o None se ffmpeg non li dà."""
    try:
        _out, err = (
            ffmpeg.input(image_path)
            .filter("scale", 160, -1)
            .filter("signalstats")
            .filter("metadata", mode="print")
            .output("-", format="null")
            .global_args("-hide_banner")
            .run(quiet=True, capture_stdout=True, capture_stderr=True)
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


def _capture(video_path: str, timestamp: float, output_path: str, output_kwargs: dict) -> bool:
    try:
        ffmpeg.input(video_path, ss=timestamp).output(output_path, **output_kwargs).overwrite_output().run(
            quiet=True, capture_stdout=True, capture_stderr=True
        )
    except ffmpeg.Error:
        logger.exception("Cattura screenshot fallita a %.1fs per %r", timestamp, video_path)
        return False
    return os.path.isfile(output_path)


def generate_screenshots(video_path: str, output_dir: str, count: int = 4, tonemap: bool = False) -> list[str]:
    """Cattura `count` frame equidistanti, escludendo il primo/ultimo 5%
    della durata (titoli/loghi/nero in apertura o coda). Un frame singolo
    che fallisce viene saltato, non blocca gli altri — solleva
    ScreenshotError solo se NESSUN frame riesce (pochi screenshot sono
    comunque meglio di un upload bloccato del tutto). tonemap=True applica
    la conversione HDR->SDR (impostazione upload_tonemap_hdr).

    Un frame nero o piatto (is_blank) si riprova qualche istante più in là
    (RETRY_OFFSETS); se lo sono tutti si tiene quello con più contrasto,
    meglio di uno screenshot in meno."""
    os.makedirs(output_dir, exist_ok=True)
    duration = _get_duration_seconds(video_path)

    margin = duration * 0.05
    usable = duration - 2 * margin
    if usable <= 0:
        margin, usable = 0.0, duration

    output_kwargs = {"vframes": 1}
    if tonemap:
        output_kwargs["vf"] = _HDR_TONEMAP_FILTER

    step = usable / (count + 1)
    paths = []
    for i in range(count):
        base = margin + step * (i + 1)
        output_path = os.path.join(output_dir, f"screenshot_{i}.png")
        best: tuple[float, str] | None = None  # (escursione, file) del tentativo migliore
        for attempt, offset in enumerate((0.0, *RETRY_OFFSETS)):
            timestamp = min(max(base + offset * step, margin), margin + usable)
            candidate = output_path if attempt == 0 else os.path.join(output_dir, f"screenshot_{i}_retry{attempt}.png")
            if not _capture(video_path, timestamp, candidate, output_kwargs):
                continue
            stats = luma_stats(candidate)
            if not is_blank(stats):
                best = (float("inf"), candidate)
                break
            logger.info("Screenshot nero o piatto a %.1fs per %r, riprovo più in là", timestamp, video_path)
            spread = stats["YMAX"] - stats["YMIN"] + stats["YAVG"] if stats else 0.0
            if best is None or spread > best[0]:
                best = (spread, candidate)
        if best is None:
            continue
        if best[1] != output_path:
            os.replace(best[1], output_path)
        paths.append(output_path)
        for leftover in os.listdir(output_dir):
            if leftover.startswith(f"screenshot_{i}_retry"):
                os.remove(os.path.join(output_dir, leftover))

    if not paths:
        raise ScreenshotError(f"Nessuno screenshot generato per {video_path!r}")
    return paths
