"""Esempi fissi per l'anteprima delle regole di naming (editor del profilo):
nomi di release e MediaInfo verosimili, passati dalle stesse funzioni di un
upload vero (nazgarr/upload_naming.py), così l'anteprima mostra davvero cosa
fanno risoluzione, {format}, tipo, sorgente, audio, lingue e sottotitoli.

- un remux UHD con Dolby Vision e tante tracce audio (TrueHD Atmos in testa),
  in tre lingue;
- un encode 1080p classico da Blu-ray, in due lingue;
- un film WEB con il solo audio originale e i sottotitoli (per le regole
  SUB/SUBS con la lingua del tracker);
- una serie di fantasia, WEB-DL da un servizio, in HDR e in più lingue.

I titoli localizzati sono fissi, per le lingue più comuni: l'anteprima non
chiama TMDB.
"""

import json
from dataclasses import dataclass, field
from types import SimpleNamespace


@dataclass(frozen=True)
class NamingExample:
    key: str
    label: str
    release_name: str
    title: str
    year: int
    content_type: str
    kind: str
    mediainfo: dict
    seasons: tuple[int, ...] = ()
    episode: int | None = None
    local_titles: dict[str, str] = field(default_factory=dict)

    def job(self) -> SimpleNamespace:
        """Quello che le funzioni del naming leggono da un UploadJob."""
        return SimpleNamespace(
            title=self.title, year=self.year, content_type=self.content_type, kind=self.kind,
            seasons_json=json.dumps(list(self.seasons)), episode=self.episode,
        )


def _audio(language: str, fmt: str, channels: int, *, features: str | None = None, title: str | None = None,
           default: bool = False) -> dict:
    return {
        "language": language, "title": title, "format": fmt, "commercial_name": None,
        "format_additional_features": features, "channels": channels, "channel_layout": None, "bit_rate": None,
        "default": default,
    }


def _subs(*languages: str) -> list[dict]:
    return [{"language": lang, "title": None, "format": "PGS", "forced": False} for lang in languages]


def _video(fmt: str, width: int, height: int, bit_depth: int, *, hdr: str | None = None,
           compatibility: str | None = None, library: str | None = None) -> dict:
    return {
        "format": fmt, "bit_depth": bit_depth, "width": width, "height": height, "scan_type": "Progressive",
        "hdr_format": hdr, "hdr_format_compatibility": compatibility,
        "transfer_characteristics": "PQ" if hdr else None, "writing_library": library,
        "encoding_settings": bool(library),
    }


EXAMPLES: tuple[NamingExample, ...] = (
    NamingExample(
        key="uhd_remux",
        label="UHD remux · DV HDR · TrueHD Atmos · 3 languages",
        release_name="Dune.Part.Two.2024.2160p.UHD.BluRay.REMUX.DV.HDR.HEVC.TrueHD.7.1.Atmos-FraMeSToR",
        title="Dune: Part Two", year=2024, content_type="movie", kind="movie",
        local_titles={"it": "Dune - Parte due", "fr": "Dune : Deuxième partie", "de": "Dune: Part Two",
                      "es": "Dune: Parte dos"},
        mediainfo={
            "video": _video("HEVC", 3840, 2160, 10, hdr="Dolby Vision, Version 1.0, Profile 7.6, BL+EL+RPU",
                            compatibility="HDR10"),
            "audio": [
                _audio("en", "MLP FBA", 8, features="16-ch", default=True),
                _audio("it", "E-AC-3", 6),
                _audio("fr", "E-AC-3", 6),
                _audio("en", "DTS", 6, features="XLL"),
                _audio("en", "AC-3", 2, title="Commentary"),
            ],
            "subtitles": _subs("en", "it", "fr", "es"),
        },
    ),
    NamingExample(
        key="fhd_encode",
        label="1080p Blu-ray encode · 2 languages",
        release_name="The.Matrix.1999.1080p.BluRay.DTS.x264-HiFi",
        title="The Matrix", year=1999, content_type="movie", kind="movie",
        local_titles={"it": "Matrix", "fr": "Matrix", "de": "Matrix", "es": "Matrix"},
        mediainfo={
            "video": _video("AVC", 1920, 800, 8, library="x264 core 164"),
            "audio": [_audio("it", "AC-3", 6, default=True), _audio("en", "DTS", 6)],
            "subtitles": _subs("it", "en"),
        },
    ),
    NamingExample(
        key="web_subbed",
        label="WEB-DL · original audio only, with subtitles",
        release_name="Perfect.Days.2023.1080p.NF.WEB-DL.AAC.2.0.H.264-GRP",
        title="Perfect Days", year=2023, content_type="movie", kind="movie",
        mediainfo={
            "video": _video("AVC", 1920, 1080, 8),
            "audio": [_audio("ja", "AAC", 2, default=True)],
            "subtitles": _subs("it", "en"),
        },
    ),
    NamingExample(
        key="series",
        label="Series · WEB-DL · HDR10 · 3 languages",
        release_name="Emberfall.S02.2160p.AMZN.WEB-DL.DDP5.1.Atmos.HDR.H.265-NTb",
        title="Emberfall", year=2023, content_type="tv", kind="season_pack", seasons=(2,),
        local_titles={"it": "Emberfall - Le terre di cenere"},
        mediainfo={
            "video": _video("HEVC", 3840, 2160, 10, hdr="SMPTE ST 2086", compatibility="HDR10"),
            "audio": [
                _audio("en", "E-AC-3", 6, features="JOC", default=True),
                _audio("it", "E-AC-3", 6),
                _audio("es", "E-AC-3", 6),
            ],
            "subtitles": _subs("it", "en", "es"),
        },
    ),
)
