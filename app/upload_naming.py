"""Nome della release per ogni tracker (docs/SPEC.md §9 "Upload flow v2"):
i segnaposto di tracker_upload_profile.naming_convention riempiti con i
valori rilevati dal nome della sorgente, corretti dagli override
dell'utente. Il nome resta una proposta: l'utente lo vede e può cambiarlo
prima di approvare.

Segnaposto: {title} {year} {season} {edition} {repack} {resolution}
{service} {source} {type} {hdr} {video_codec} {audio_codec} {group}.
Un segnaposto senza valore sparisce, con gli spazi e le parentesi rimasti
vuoti. {season} (S02, S01-S03, S02E03) si aggiunge da solo dopo titolo e
anno per le serie, se il profilo non lo prevede.
"""

import re

import guessit

from app.upload_dupes import traits_of

# Campi degli override che l'utente può correggere, gli stessi rilevati qui.
DETECTED_FIELDS = (
    "type", "resolution", "source", "edition", "repack", "service", "hdr", "video_codec", "audio_codec", "group",
)

_SERVICES = {
    "Netflix": "NF", "Amazon Prime": "AMZN", "Apple TV+": "ATVP", "AppleTV": "ATVP", "Disney+": "DSNP",
    "Disney Plus": "DSNP", "HBO Max": "HMAX",
    "Max": "MAX", "Hulu": "HULU", "Paramount+": "PMTP", "Peacock": "PCOK", "Now TV": "NOW", "NowTV": "NOW",
    "Sky": "SKY", "RaiPlay": "RAI", "Crunchyroll": "CR", "iTunes": "iT",
}
_AUDIO = {
    "Dolby Digital Plus": "DDP", "Dolby Digital": "DD", "Dolby TrueHD": "TrueHD", "DTS-HD": "DTS-HD",
    "DTS": "DTS", "AAC": "AAC", "FLAC": "FLAC", "Opus": "Opus", "MP3": "MP3", "PCM": "LPCM",
}


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def release_type(guess: dict) -> str:
    """Chiave type_id dei profili (REMUX, ENCODE, WEBDL, ...): la stessa
    euristica di app/upload.py, qui su un guessit già calcolato."""
    others = {str(o) for o in _as_list(guess.get("other"))}
    source = str(guess.get("source") or "").lower()
    if "Remux" in others:
        return "REMUX"
    if source == "web":
        return "WEBRIP" if "Rip" in others else "WEBDL"
    if source == "hdtv":
        return "HDTV"
    if source == "dvd":
        return "DVDRIP"
    return "ENCODE"


def _source_label(guess: dict) -> str | None:
    source = str(guess.get("source") or "")
    others = {str(o) for o in _as_list(guess.get("other"))}
    if source == "Web":
        return "WEBRip" if "Rip" in others else "WEB-DL"
    if source == "Ultra HD Blu-ray":
        return "UHD BluRay"
    if source == "Blu-ray":
        return "BluRay"
    return source or None


def _video_codec(guess: dict, release: str) -> str | None:
    codec = str(guess.get("video_codec") or "")
    # Un encode si scrive x264/x265, una sorgente non ricodificata H.264/H.265
    # (AVC/HEVC per i remux): la convenzione più diffusa, sempre correggibile.
    if codec == "H.264":
        return {"REMUX": "AVC", "ENCODE": "x264", "WEBRIP": "x264"}.get(release, "H.264")
    if codec == "H.265":
        return {"REMUX": "HEVC", "ENCODE": "x265", "WEBRIP": "x265"}.get(release, "H.265")
    return codec or None


def _audio(guess: dict) -> str | None:
    codecs = [str(c) for c in _as_list(guess.get("audio_codec"))]
    atmos = "Dolby Atmos" in codecs
    main = next((c for c in codecs if c != "Dolby Atmos"), None)
    label = _AUDIO.get(main or "", main)
    if label == "DTS-HD" and "Master Audio" in {str(p) for p in _as_list(guess.get("audio_profile"))}:
        label = "DTS-HD MA"
    if label is None:
        return "Atmos" if atmos else None
    channels = guess.get("audio_channels")
    parts = [label + (str(channels) if channels and label in ("DDP", "DD", "AAC") else "")]
    if channels and label not in ("DDP", "DD", "AAC"):
        parts.append(str(channels))
    if atmos:
        parts.append("Atmos")
    return " ".join(parts)


def detect(source_name: str) -> dict:
    """I valori che si leggono dal nome della sorgente: il placeholder di
    ogni campo "Detected details", e la base del nome proposto."""
    guess = guessit.guessit(source_name)
    traits = traits_of(source_name)
    release = release_type(guess)
    service = guess.get("streaming_service")
    hdr = " ".join(tag for tag in ("DV", "HDR") if tag in traits.hdr) or None
    edition = " ".join(str(e) for e in _as_list(guess.get("edition"))) or None
    return {
        "type": release,
        "resolution": guess.get("screen_size"),
        "source": _source_label(guess),
        "edition": edition,
        "repack": "REPACK" if traits.repack else None,
        "service": _SERVICES.get(str(service), str(service)) if service else None,
        "hdr": hdr,
        "video_codec": _video_codec(guess, release),
        "audio_codec": _audio(guess),
        "group": guess.get("release_group"),
    }


def season_token(kind: str, seasons: list[int], episode: int | None) -> str | None:
    if not seasons:
        return None
    if kind == "episode" and episode is not None:
        return f"S{seasons[0]:02d}E{episode:02d}"
    if kind == "complete_pack" and len(seasons) > 1:
        return f"S{min(seasons):02d}-S{max(seasons):02d}"
    return f"S{seasons[0]:02d}"


_TOKEN = re.compile(r"\{(\w+)\}")


def build_name(convention: str | None, values: dict) -> str:
    template = convention or "{title} ({year}) {season} {resolution} {source} {video_codec} {audio_codec} {group}"
    if values.get("season") and "{season}" not in template:
        anchor = "({year})" if "({year})" in template else "{year}" if "{year}" in template else "{title}"
        template = template.replace(anchor, f"{anchor} {{season}}", 1)
    # Un tag del gruppo finisce attaccato con il trattino, come nei nomi di release.
    group = values.get("group")
    rendered = _TOKEN.sub(lambda m: "" if m.group(1) == "group" else str(values.get(m.group(1)) or ""), template)
    rendered = re.sub(r"\(\s*\)|\[\s*\]", "", rendered)
    rendered = re.sub(r"\s+", " ", rendered).strip()
    if group and "{group}" in template:
        rendered = f"{rendered}-{group}"
    return rendered


def name_values(job, detected: dict, overrides: dict, seasons: list[int]) -> dict:
    """Titolo, anno e stagione dal match confermato, il resto dai valori
    rilevati con sopra gli override (un override vuoto non conta)."""
    values = {key: detected.get(key) for key in DETECTED_FIELDS}
    for key in DETECTED_FIELDS:
        if overrides.get(key) not in (None, ""):
            values[key] = overrides[key]
    values["title"] = job.title
    values["year"] = overrides.get("year") or job.year
    values["season"] = season_token(job.kind or "movie", seasons, job.episode) if job.content_type == "tv" else None
    return values
