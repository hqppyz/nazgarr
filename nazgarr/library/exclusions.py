"""Esclusioni: file che non vanno mostrati (di default) né conteggiati
nelle statistiche di Library/Torrent — un concetto distinto dallo stato
"ignored" già esistente (client_torrent_file senza hardlink, sezione 3):
qui si tratta di file spazzatura (nfo scena, sample, file incompleti di
un client) che non sono contenuto reale, indipendentemente dal loro stato
seeding/orfano.

Sintassi pattern (fnmatch, case-insensitive), applicata sia al nome file
sia al relative_path intero — un pattern senza "/" matcha ovunque nel path
(qualunque segmento), uno con "/" matcha solo quel percorso relativo:
  *.nfo          -> qualunque file .nfo, a qualunque profondità
  sample/*       -> qualunque file dentro una cartella "sample"
  *.!qb          -> file incompleti qBittorrent (case-insensitive)
"""

import fnmatch
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from nazgarr.core import settings_repo

# Preset per file "sidecar" dei client torrent più comuni — l'estensione
# temporanea che ciascun client aggiunge a un file non ancora completo.
# Non sono file di stato del client (.fastresume etc, quelli vivono nella
# config dir del client, mai dentro la cartella dei torrent) ma sidecar
# per-file dentro il contenuto stesso.
CLIENT_INCOMPLETE_PRESETS: dict[str, list[str]] = {
    "qbittorrent_incomplete": ["*.!qb"],
    "utorrent_incomplete": ["*.!ut"],
    "bitcomet_incomplete": ["*.bc!"],
}

# Spazzatura tipica di una release scena/tracker, mai il contenuto vero.
SCENE_JUNK_PRESET = "scene_junk"

# Metadati che media server e *arr scrivono accanto ai video in libreria
# (poster, fanart, nfo Kodi/Radarr/Sonarr): mai parte di un torrent, ma da
# quando lo scanner registra ogni file lato libreria renderebbero la vista
# Media files illeggibile. Attivo di default finché l'utente non salva le
# proprie scelte (DEFAULT_ENABLED_PRESETS).
MEDIA_SERVER_METADATA_PRESET = "media_server_metadata"

PRESETS: dict[str, list[str]] = {
    **CLIENT_INCOMPLETE_PRESETS,
    SCENE_JUNK_PRESET: [
        "*.nfo", "*.sfv", "*.txt", "*.diz",
        "sample/*", "sample.*", "*-sample.*",
        "proof/*",
        "screens/*", "screenshots/*",
        "*thumbs.db", "*.ds_store",
    ],
    MEDIA_SERVER_METADATA_PRESET: [
        "poster.*", "fanart.*", "banner.*", "clearlogo.*", "clearart.*", "landscape.*", "logo.*",
        "folder.jpg", "folder.png", "*-thumb.jpg", "*-poster.*", "*-fanart.*",
        "season*-poster.*", "season*-banner.*", "season*-fanart.*",
        "theme.mp3", ".actors/*", "*.nfo",
    ],
}

# Preset attivi quando exclusion_presets non è mai stato salvato (None).
# Una stringa vuota salvata dall'utente significa invece "nessuno".
DEFAULT_ENABLED_PRESETS = [MEDIA_SERVER_METADATA_PRESET]


@dataclass
class CompiledExclusions:
    patterns: list[str]

    def __post_init__(self) -> None:
        # Tutti i pattern in due espressioni regolari, compilate una volta:
        # is_excluded gira su ogni file della libreria a ogni vista e a ogni
        # fotografia della salute (decine di migliaia di chiamate).
        by_name, by_path = [], []
        for pattern in self.patterns:
            p = pattern.lower()
            if "/" not in p:
                by_name.append(fnmatch.translate(p))
            else:
                # Un pattern con "/" matcha da qualunque profondità, non solo
                # dalla radice — "sample/*" deve prendere sia "sample/x.mkv"
                # sia "Movie/sample/x.mkv", non solo il primo.
                by_path.extend((fnmatch.translate(p), fnmatch.translate(f"*/{p}")))
        self._by_name = re.compile("|".join(by_name)) if by_name else None
        self._by_path = re.compile("|".join(by_path)) if by_path else None

    def is_excluded(self, relative_path: str) -> bool:
        if not self.patterns:
            return False
        normalized = relative_path.replace("\\", "/").lower()
        if self._by_name is not None and self._by_name.match(normalized.rsplit("/", 1)[-1]):
            return True
        return self._by_path is not None and self._by_path.match(normalized) is not None


def parse_custom_patterns(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def parse_preset_keys(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [key.strip() for key in raw.split(",") if key.strip()]


def compile_exclusions(custom_patterns_raw: str | None, enabled_presets_raw: str | None) -> CompiledExclusions:
    patterns = list(parse_custom_patterns(custom_patterns_raw))
    preset_keys = DEFAULT_ENABLED_PRESETS if enabled_presets_raw is None else parse_preset_keys(enabled_presets_raw)
    for key in preset_keys:
        patterns.extend(PRESETS.get(key, []))
    return CompiledExclusions(patterns=patterns)


def load_exclusions(session: Session) -> CompiledExclusions:
    """Esclusioni correnti da app_settings (editabili da Configuration >
    Exclusions). Una sola lettura per chiamante: la vista Library la fa a
    ogni richiesta, la pipeline una volta per fase — risoluzione TMDB e
    matching saltano i file esclusi, lo scanner invece li registra comunque
    (così "Show excluded" funziona e cambiare un pattern non richiede un
    nuovo scan)."""
    return compile_exclusions(
        settings_repo.get_setting(session, "exclusion_patterns"),
        settings_repo.get_setting(session, "exclusion_presets"),
    )

