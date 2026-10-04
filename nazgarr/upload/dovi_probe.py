"""Dolby Vision letto dal flusso video quando MediaInfo non lo vede
(decisione dell'utente, 2026-10-03).

MediaInfo riconosce il Dolby Vision dal record di configurazione che il
contenitore dichiara (dvcC/dvvC). Un file con l'RPU in ogni fotogramma ma
senza quel record, ad esempio tagliato o rimuxato da uno strumento che non
lo riscrive, risulta solo HDR10 o HDR10+ (MediaArea/MediaInfo #1312), e il
nome della release perderebbe "DV" e il suo profilo. ffprobe invece legge
il primo fotogramma e vi trova l'RPU, come fanno dovi_tool e gli script di
rename per ITT.

Solo come ripiego: si chiama ffprobe soltanto se MediaInfo non ha trovato
il Dolby Vision e il video può averlo (HEVC, AVC o AV1 a 10 bit o più).
Sola lettura, con un timeout; se ffprobe manca o fallisce, il riepilogo di
MediaInfo resta com'è.
"""

import json
import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60
# I primi pacchetti, non solo il primo: in un MP4 con i B-frame il primo
# pacchetto non dà ancora un fotogramma decodificato (e niente RPU).
PACKETS = 16
_DV_CODECS = ("HEVC", "AVC", "AV1")


def _side_data(path: str) -> list[dict] | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    command = [
        ffprobe, "-v", "quiet", "-print_format", "json", "-select_streams", "v:0",
        "-show_streams", "-show_frames", "-read_intervals", f"%+#{PACKETS}", path,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
        data = json.loads(result.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        logger.warning("ffprobe non è riuscito a leggere %r", path, exc_info=True)
        return None
    items = []
    for stream in data.get("streams", [])[:1]:
        items.extend(stream.get("side_data_list") or [])
    for frame in data.get("frames", []):
        items.extend(frame.get("side_data_list") or [])
    return items


def _is_dovi(item: dict) -> bool:
    kind = str(item.get("side_data_type") or "").lower()
    return "dovi" in kind or "dolby vision" in kind


def probe(path: str) -> dict | None:
    """{"profile": int | None} se il flusso porta il Dolby Vision, None se no
    (o se non si è potuto leggere). Il profilo viene dal record di
    configurazione (dv_profile) se ffmpeg lo espone, o dall'RPU come lo
    stima dovi_tool: profilo RPU 0 è il profilo 5; profilo RPU 1 è il 7 con
    lo strato di enhancement (residual attivo) e l'8 senza. Altrimenti None
    ("DV" nel nome, da completare a mano)."""
    items = _side_data(path)
    if not items:
        return None
    dovi = [item for item in items if _is_dovi(item)]
    if not dovi:
        return None
    for item in dovi:
        if item.get("dv_profile") is not None:
            return {"profile": int(item["dv_profile"])}
    for item in dovi:
        rpu_profile = str(item.get("vdr_rpu_profile"))
        if rpu_profile == "0":
            return {"profile": 5}
        if rpu_profile == "1" and item.get("disable_residual_flag") is not None:
            return {"profile": 8 if str(item["disable_residual_flag"]) == "1" else 7}
    return {"profile": None}


def may_have_dolby_vision(video: dict | None) -> bool:
    if not video:
        return False
    text = " ".join(str(video.get(key) or "") for key in ("hdr_format", "hdr_format_profile", "hdr_format_string"))
    if "dolby vision" in text.lower():
        return False  # MediaInfo l'ha già visto
    return str(video.get("format") or "").upper() in _DV_CODECS and (video.get("bit_depth") or 0) >= 10


def complete(summary: dict | None, path: str) -> bool:
    """Aggiunge al riepilogo di MediaInfo il Dolby Vision trovato nel flusso,
    nella stessa forma in cui lo scrive MediaInfo ("Dolby Vision, ..." in
    hdr_format, "dvhe.0N" nel profilo), così i nomi lo leggono come sempre.
    True se l'ha aggiunto."""
    video = (summary or {}).get("video")
    if not may_have_dolby_vision(video):
        return False
    found = probe(path)
    if found is None:
        return False
    previous = video.get("hdr_format")
    video["hdr_format"] = "Dolby Vision" + (f", {previous}" if previous else "")
    if found["profile"] is not None:
        video["hdr_format_profile"] = f"dvhe.{found['profile']:02d}" + (
            f" / {video['hdr_format_profile']}" if video.get("hdr_format_profile") else "")
    video["dolby_vision_from_stream"] = True
    return True
