"""Nome della release per ogni tracker (docs/SPEC.md §9 "Upload flow v2").

Due metà:
- i VALORI: letti dal MediaInfo quando c'è (risoluzione, codec video, HDR,
  tracce audio e lingue, sottotitoli) e dal nome della release (tipo,
  sorgente, servizio, edizione, repack, gruppo: il nome scelto dall'analisi,
  app/upload_analysis.py name_source), con sopra gli override dell'utente;
- le REGOLE del tracker (tracker_upload_profile.naming_rules_json, versionate
  nei profili bundlati, app/upload_profiles.py): un template per tipo di
  release, come vuole il tracker, più poche opzioni (titolo locale, come
  scrivere audio e lingue, etichetta SDR, separatore).

Segnaposto dei template: VARIABLES qui sotto, le stesse per ogni tracker.
Un segnaposto senza valore
sparisce con gli spazi rimasti; {season} si aggiunge da solo dopo titolo e
anno per le serie se il template non lo prevede; il gruppo si attacca alla
fine con group_separator. Il nome resta una proposta, sempre modificabile.
"""

import json
import re

import guessit

from app.upload_dupes import traits_of

# Le variabili dei template, uguali per tutti i tracker, con un esempio:
# servono all'editor delle regole (chip da inserire e anteprima).
VARIABLES = {
    "title": "Dune: Part Two", "local_title": "Dune - Parte due", "year": "2024", "season": "S02",
    "episode": "E03", "edition": "Extended", "repack": "REPACK", "resolution": "2160p", "source": "UHD BluRay",
    "type": "REMUX", "service": "ATVP", "video_codec": "HEVC", "hdr": "DV HDR", "bit_depth": "10bit",
    "audio": "TrueHD 7.1 Atmos", "audio_codec": "TrueHD", "audio_channels": "7.1", "audio_atmos": "Atmos",
    "audio_all": "TrueHD 7.1 Atmos DD+ 5.1", "audio_languages": "ITA ENG", "subs_languages": "ITA ENG",
    "subs": "SUBS ITA ENG", "group": "GRP",
}

# Campi che l'utente può correggere nei "Detected details".
DETECTED_FIELDS = (
    "type", "resolution", "source", "edition", "repack", "service", "hdr", "video_codec", "audio",
    "audio_languages", "group",
)

DEFAULT_TEMPLATE = "{title} ({year}) {season} {resolution} {source} {video_codec} {audio} {group}"
# Come si scrive {type} nel nome: la chiave del profilo (REMUX, WEBDL, ...)
# resta per scegliere il type_id, nel nome va la sua etichetta. Un profilo
# può ridefinirla (rules.type_labels), anche con variabili dentro, es.
# REMUX: "{source} REMUX VU"; vuota = nel nome non si scrive.
DEFAULT_TYPE_LABELS = {
    "REMUX": "REMUX", "WEBDL": "WEB-DL", "WEBRIP": "WEBRip", "ENCODE": "", "HDTV": "HDTV", "DVDRIP": "DVDRip",
    "BRRIP": "BRRip", "DISC": "",
}
DEFAULT_RULES = {
    "version": 0,
    "templates": {"default": DEFAULT_TEMPLATE},
    "title": "original",  # original | local | local_original (titolo originale seguito da quello locale)
    "title_language": None,  # es. "it": titolo TMDB in quella lingua per {local_title}
    "audio_languages": {"style": "none"},  # none | all | primary_first (+ primary, multi_from)
    "subs_languages": {"style": "all"},  # come audio_languages, per {subs_languages}
    "subs_format": "SUBS {subs_languages}",  # come si scrive {subs} se ci sono sottotitoli; "" = mai
    "sdr_label": None,  # es. "SDR": scritto al posto dell'HDR quando non c'è
    "separator": " ",
    "group_separator": "-",
}

_SERVICES = {
    "Netflix": "NF", "Amazon Prime": "AMZN", "Apple TV+": "ATVP", "AppleTV": "ATVP", "Disney+": "DSNP",
    "Disney Plus": "DSNP", "HBO Max": "HMAX", "Max": "MAX", "Hulu": "HULU", "Paramount+": "PMTP",
    "Peacock": "PCOK", "Now TV": "NOW", "NowTV": "NOW", "Sky": "SKY", "RaiPlay": "RAI", "Crunchyroll": "CR",
    "iTunes": "iT",
}
_NAME_AUDIO = {
    "Dolby Digital Plus": "DD+", "Dolby Digital": "DD", "Dolby TrueHD": "TrueHD", "DTS-HD": "DTS-HD",
    "DTS": "DTS", "AAC": "AAC", "FLAC": "FLAC", "Opus": "Opus", "MP3": "MP3", "PCM": "LPCM",
}
# Formato MediaInfo -> nome usato nelle release. Un profilo può
# ridefinirlo (rules.audio_codecs), es. "DDP" invece di "DD+".
DEFAULT_AUDIO_CODECS = {
    "MLP FBA": "TrueHD", "E-AC-3": "DD+", "AC-3": "DD", "DTS": "DTS", "DTS-HD MA": "DTS-HD MA",
    "DTS-HD HRA": "DTS-HD HRA", "DTS:X": "DTS:X", "AAC": "AAC", "FLAC": "FLAC", "PCM": "LPCM", "Opus": "Opus",
    "MPEG Audio": "MP3", "Vorbis": "Vorbis",
}
# ISO 639-1 (MediaInfo) -> codice a tre lettere scritto nei nomi.
_LANG3 = {
    "it": "ITA", "en": "ENG", "fr": "FRA", "de": "DEU", "es": "SPA", "pt": "POR", "ja": "JPN", "ko": "KOR",
    "zh": "ZHO", "ru": "RUS", "nl": "NLD", "sv": "SWE", "da": "DAN", "no": "NOR", "nb": "NOR", "fi": "FIN",
    "pl": "POL", "cs": "CES", "hu": "HUN", "tr": "TUR", "el": "ELL", "he": "HEB", "ar": "ARA", "hi": "HIN",
    "th": "THA", "uk": "UKR", "ro": "RON",
}


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def release_type(guess: dict) -> str:
    """Chiave type_id dei profili (REMUX, ENCODE, WEBDL, ...)."""
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


def _name_video_codec(guess: dict, release: str) -> str | None:
    codec = str(guess.get("video_codec") or "")
    # Un encode si scrive x264/x265, una sorgente non ricodificata H.264/H.265
    # (AVC/HEVC per i remux): la convenzione più diffusa, sempre correggibile.
    if codec == "H.264":
        return {"REMUX": "AVC", "ENCODE": "x264", "WEBRIP": "x264"}.get(release, "H.264")
    if codec == "H.265":
        return {"REMUX": "HEVC", "ENCODE": "x265", "WEBRIP": "x265"}.get(release, "H.265")
    return codec or None


def _name_audio(guess: dict) -> str | None:
    codecs = [str(c) for c in _as_list(guess.get("audio_codec"))]
    atmos = "Dolby Atmos" in codecs
    main = next((c for c in codecs if c != "Dolby Atmos"), None)
    label = _NAME_AUDIO.get(main or "", main)
    if label == "DTS-HD" and "Master Audio" in {str(p) for p in _as_list(guess.get("audio_profile"))}:
        label = "DTS-HD MA"
    if label is None:
        return "Atmos" if atmos else None
    parts = [label]
    if guess.get("audio_channels"):
        parts.append(str(guess["audio_channels"]))
    if atmos:
        parts.append("Atmos")
    return " ".join(parts)


def detect(source_name: str) -> dict:
    """I valori che si leggono dal nome della release."""
    guess = guessit.guessit(source_name)
    traits = traits_of(source_name)
    release = release_type(guess)
    service = guess.get("streaming_service")
    return {
        "type": release,
        "resolution": guess.get("screen_size"),
        "source": _source_label(guess),
        "edition": " ".join(str(e) for e in _as_list(guess.get("edition"))) or None,
        "repack": "REPACK" if traits.repack else None,
        "service": _SERVICES.get(str(service), str(service)) if service else None,
        "hdr": " ".join(tag for tag in ("DV", "HDR") if tag in traits.hdr) or None,
        "video_codec": _name_video_codec(guess, release),
        "audio": _name_audio(guess),
        "audio_languages": None,
        "group": guess.get("release_group"),
    }


# --- dal MediaInfo --------------------------------------------------------------


def _mi_resolution(video: dict) -> str | None:
    width, height = video.get("width") or 0, video.get("height") or 0
    if not width and not height:
        return None
    interlaced = str(video.get("scan_type") or "").lower() in ("interlaced", "mbaff", "paff")
    if height >= 2000 or width >= 3800:
        base = "2160"
    elif height >= 1000 or width >= 1900:
        base = "1080"
    elif height >= 700 or width >= 1260:
        base = "720"
    elif height >= 560:
        base = "576"
    else:
        base = "480"
    return f"{base}{'i' if interlaced and base in ('1080', '576', '480') else 'p'}"


def _mi_hdr(video: dict) -> str | None:
    hdr = f"{video.get('hdr_format') or ''} {video.get('hdr_format_compatibility') or ''}"
    transfer = str(video.get("transfer_characteristics") or "")
    tags = []
    if "Dolby Vision" in hdr:
        tags.append("DV")
    if "HDR10+" in hdr or "2094" in hdr:
        tags.append("HDR10+")
    elif "HDR10" in hdr or "2086" in hdr or "PQ" in transfer:
        tags.append("HDR")
    if "HLG" in transfer or "HLG" in hdr:
        tags.append("HLG")
    return " ".join(tags) or None


def _mi_video_codec(video: dict, release: str) -> str | None:
    fmt = str(video.get("format") or "")
    library = str(video.get("writing_library") or "").lower()
    encoded = "x264" in library or "x265" in library or bool(video.get("encoding_settings"))
    web = release in ("WEBDL", "WEBRIP", "HDTV")
    if fmt == "AVC":
        return "x264" if encoded else ("H.264" if web else "AVC")
    if fmt == "HEVC":
        return "x265" if encoded else ("H.265" if web else "HEVC")
    if fmt == "MPEG Video":
        return "MPEG-2"
    return fmt or None


def _audio_codec_key(track: dict) -> str | None:
    fmt = str(track.get("format") or "")
    features = str(track.get("format_additional_features") or "")
    if fmt == "DTS":
        if "XLL X" in features:
            return "DTS:X"
        if "XLL" in features:
            return "DTS-HD MA"
        if "XBR" in features:
            return "DTS-HD HRA"
    return fmt or None


def _audio_parts(track: dict, codecs: dict) -> tuple[str | None, str | None, str | None]:
    """(codec, canali, "Atmos") di una traccia, come si scrivono nei nomi."""
    key = _audio_codec_key(track)
    codec = codecs.get(key, key) if key else None
    channels = track.get("channels")
    layout_channels = None
    if channels:
        layout = str(track.get("channel_layout") or "")
        lfe = "LFE" in layout if layout else channels >= 6
        layout_channels = f"{channels - 1}.1" if lfe else f"{channels}.0"
    features = f"{track.get('format_additional_features') or ''} {track.get('commercial_name') or ''}"
    atmos = "Atmos" if ("Atmos" in features or "JOC" in features or "16-ch" in features) else None
    return codec, layout_channels, atmos


def _audio_label(track: dict, codecs: dict) -> str | None:
    codec, channels, atmos = _audio_parts(track, codecs)
    if codec is None:
        return None
    return " ".join(part for part in (codec, channels, atmos) if part)


def _is_commentary(track: dict) -> bool:
    return "comment" in str(track.get("title") or "").lower()


def _audio_values(tracks: list[dict], rules: dict) -> dict:
    codecs = {**DEFAULT_AUDIO_CODECS, **(rules.get("audio_codecs") or {})}
    usable = [t for t in tracks if not _is_commentary(t)]
    if not usable:
        return {}
    main = next((t for t in usable if t.get("default")), usable[0])
    codec, channels, atmos = _audio_parts(main, codecs)
    # Stesso codec e stessi canali una volta sola (due tracce DD 5.1 in lingue
    # diverse sono "DD 5.1", le lingue le dice {audio_languages}).
    labels = dict.fromkeys(label for label in (_audio_label(t, codecs) for t in usable) if label)
    every = " ".join(labels) or None
    return {
        "audio": every if rules.get("audio") == "all" else _audio_label(main, codecs),  # "all": regole v1
        "audio_codec": codec, "audio_channels": channels, "audio_atmos": atmos, "audio_all": every,
    }


def _lang3(language: str) -> str:
    code = language.split("-")[0].lower()
    return _LANG3.get(code, code.upper()[:3])


def _languages_value(tracks: list[dict], config: dict | None) -> str | None:
    config = config or {"style": "none"}
    style = config.get("style", "none")
    if style == "none":
        return None
    langs = list(dict.fromkeys(_lang3(t["language"]) for t in tracks if t.get("language") and not _is_commentary(t)))
    if not langs:
        return None
    # Da multi_from lingue in su, "MULTI" al posto dell'elenco; con
    # primary_first la lingua principale del tracker resta davanti.
    many = len(langs) >= (config.get("multi_from") or 99)
    if style == "all":
        return "MULTI" if many else " ".join(langs)
    primary = config.get("primary")
    head = [primary] if primary in langs else []
    if many:
        return " ".join([*head, "MULTI"])
    return " ".join([*head, *(lang for lang in langs if lang != primary)])


def season_token(kind: str, seasons: list[int], episode: int | None) -> str | None:
    if not seasons:
        return None
    if kind == "episode" and episode is not None:
        return f"S{seasons[0]:02d}E{episode:02d}"
    if kind == "complete_pack" and len(seasons) > 1:
        return f"S{min(seasons):02d}-S{max(seasons):02d}"
    return f"S{seasons[0]:02d}"


def effective_rules(rules: dict | None) -> dict:
    return {**DEFAULT_RULES, **(rules or {})}


def release_values(
    job, detected: dict, mediainfo: dict | None, overrides: dict, rules: dict | None, local_title: str | None = None
) -> dict:
    """Tutti i valori dei segnaposto per un tracker: MediaInfo, poi il nome
    della release, poi gli override dell'utente sopra tutto."""
    rules_in = rules
    rules = effective_rules(rules)
    values = {key: detected.get(key) for key in DETECTED_FIELDS}
    video = (mediainfo or {}).get("video") or {}
    tracks = (mediainfo or {}).get("audio") or []
    subtitles = (mediainfo or {}).get("subtitles") or []
    release = overrides.get("type") or values["type"] or "ENCODE"
    if video:
        values["resolution"] = _mi_resolution(video) or values["resolution"]
        values["video_codec"] = _mi_video_codec(video, release) or values["video_codec"]
        values["hdr"] = _mi_hdr(video)
        values["bit_depth"] = f"{video['bit_depth']}bit" if video.get("bit_depth") else None
    if tracks:
        audio = _audio_values(tracks, rules)
        values.update({k: v for k, v in audio.items() if k != "audio"})
        values["audio"] = audio.get("audio") or values["audio"]
        values["audio_languages"] = _languages_value(tracks, rules.get("audio_languages"))
    # Senza MediaInfo le tracce le dice solo il nome della release.
    values["audio_all"] = values.get("audio_all") or values.get("audio")
    if subtitles:
        values["subs_languages"] = _languages_value(subtitles, rules.get("subs_languages") or {"style": "all"})
    if not values.get("hdr") and rules.get("sdr_label"):
        values["hdr"] = rules["sdr_label"]
    values["subs"] = None
    if subtitles:
        # Regole v1-v3 avevano solo un'etichetta fissa (subs_label).
        subs_format = rules.get("subs_format")
        if "subs_format" not in (rules_in or {}) and (rules_in or {}).get("subs_label"):
            subs_format = rules_in["subs_label"]
        values["subs"] = re.sub(r"\s+", " ", _render(subs_format or "", values)).strip() or None
    for key in DETECTED_FIELDS:
        if overrides.get(key) not in (None, ""):
            values[key] = overrides[key]

    title = job.title
    if rules.get("title") == "local" and local_title:
        title = local_title
    elif rules.get("title") == "local_original" and local_title and local_title != job.title:
        title = f"{job.title} {local_title}"
    values["title"] = title
    values["content_type"] = job.content_type
    values["local_title"] = local_title if local_title and local_title != job.title else None
    values["year"] = overrides.get("year") or job.year
    seasons = json.loads(job.seasons_json or "[]")
    values["season"] = season_token(job.kind or "movie", seasons, job.episode) if job.content_type == "tv" else None
    values["episode"] = f"E{job.episode:02d}" if job.kind == "episode" and job.episode is not None else None
    return values


_TOKEN = re.compile(r"\{(\w+)\}")


def template_for(rules: dict, release_type_key: str | None, content_type: str | None = None) -> str:
    """Il pattern per le serie se è una serie e il profilo ne ha uno (di
    solito senza anno), poi quello del tipo di release, poi il principale."""
    templates = rules.get("templates") or {}
    for key in (("tv",) if content_type == "tv" else ()) + ((release_type_key,) if release_type_key else ()):
        template = (templates.get(key) or "").strip()
        if template:
            return template
    return templates.get("default") or DEFAULT_TEMPLATE


def _render(template: str, values: dict) -> str:
    return _TOKEN.sub(lambda m: "" if m.group(1) == "group" else str(values.get(m.group(1)) or ""), template)


def type_label(rules: dict, values: dict) -> str | None:
    key = values.get("type")
    if not key:
        return None
    labels = {**DEFAULT_TYPE_LABELS, **(rules.get("type_labels") or {})}
    label = labels.get(key, key)
    return re.sub(r"\s+", " ", _render(label, {**values, "type": key})).strip() or None


def build_name(rules: dict | None, values: dict) -> str:
    rules = effective_rules(rules)
    template = template_for(rules, values.get("type"), values.get("content_type"))
    values = {**values, "type": type_label(rules, values)}
    if values.get("season") and "{season}" not in template:
        anchor = "({year})" if "({year})" in template else "{year}" if "{year}" in template else "{title}"
        template = template.replace(anchor, f"{anchor} {{season}}", 1)
    group = values.get("group")
    rendered = _render(template, values)
    rendered = re.sub(r"\(\s*\)|\[\s*\]", "", rendered)
    rendered = re.sub(r"\s+", " ", rendered).strip()
    separator = rules.get("separator") or " "
    if separator != " ":
        rendered = rendered.replace(" ", separator)
    if group and "{group}" in template:
        rendered = f"{rendered}{rules.get('group_separator') or '-'}{group}"
    return rendered


def rules_from_convention(convention: str | None) -> dict | None:
    """Un profilo senza regole ma con il vecchio naming_convention: quello
    come template unico."""
    return {"templates": {"default": convention}} if convention else None
