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

# Artwork e metadati che Plex, Jellyfin, Kodi e gli *arr scrivono accanto ai
# video. Dalle documentazioni (2026-10-05): Plex "Local Media Assets" (film e
# serie) e Jellyfin "Movies"/"Shows". Le immagini si escludono per estensione,
# nei formati che leggono (jpg, jpeg, png, tbn; webp per Jellyfin): Plex
# accetta anche artwork chiamato come il video ("Avatar (2009).jpg", la
# miniatura di un episodio) o numerato ("poster-2.png", "Season01a.jpg"),
# nomi che nessun elenco copre, e in una cartella di media un'immagine non è
# mai il contenuto. Poi i file nfo, la musica e i video del tema.
MEDIA_SERVER_METADATA_PRESET = "media_server_metadata"

# Extra (trailer, featurette, scene eliminate...) come li nominano Plex
# ("Local Files for Trailers and Extras") e Jellyfin: le cartelle e i
# suffissi. Spento di default: sono video veri. Escluderli li toglie solo
# dalle viste e dalla ricerca come file a sé; un pack che li contiene li
# ricrea comunque con un hardlink (nazgarr/torrents/layout.py).
EXTRAS_PRESET = "extras"

# File di sistema di macOS (AppleDouble "._", .DS_Store, cartelle nascoste
# dei volumi) e di Windows, che finiscono nelle cartelle condivise.
SYSTEM_FILES_PRESET = "system_files"

# I .torrent lasciati accanto ai file: mai contenuto.
TORRENT_FILES_PRESET = "torrent_files"

_EXTRA_FOLDERS = ("behind the scenes", "deleted scenes", "featurettes", "interviews", "scenes", "shorts",
                  "trailers", "clips", "other", "extras", "samples")
_EXTRA_SUFFIXES = ("-trailer", ".trailer", "_trailer", " trailer", "-scene", "-clip", "-interview",
                   "-behindthescenes", "-deleted", "-deletedscene", "-featurette", "-short", "-other", "-extra")

# In quest'ordine nella UI (Impostazioni › Esclusioni).
PRESETS: dict[str, list[str]] = {
    SCENE_JUNK_PRESET: [
        "*.nfo", "*.sfv", "*.txt", "*.diz",
        "sample/*", "sample.*", "*-sample.*",
        "proof/*",
        "screens/*", "screenshots/*",
    ],
    MEDIA_SERVER_METADATA_PRESET: [
        "*.jpg", "*.jpeg", "*.png", "*.tbn", "*.webp",
        "*.nfo",
        "theme.*", "theme-music/*", "backdrops/*",
        ".actors/*",
    ],
    EXTRAS_PRESET: [
        *(f"{folder}/*" for folder in _EXTRA_FOLDERS),
        *(f"*{suffix}.*" for suffix in _EXTRA_SUFFIXES),
        "trailer.*",
    ],
    SYSTEM_FILES_PRESET: [
        "._*", ".ds_store", ".appledouble/*", ".spotlight-v100/*", ".trashes/*", ".fseventsd/*",
        ".temporaryitems/*", ".documentrevisions-v100/*", "icon\r", ".localized",
        "thumbs.db", "desktop.ini", "$recycle.bin/*", "system volume information/*",
    ],
    TORRENT_FILES_PRESET: ["*.torrent"],
    **CLIENT_INCOMPLETE_PRESETS,
}
# I preset della libreria per primi.
PRESETS = {key: PRESETS[key] for key in (MEDIA_SERVER_METADATA_PRESET, EXTRAS_PRESET, SYSTEM_FILES_PRESET,
                                         TORRENT_FILES_PRESET, SCENE_JUNK_PRESET, *CLIENT_INCOMPLETE_PRESETS)}

# Preset attivi quando exclusion_presets non è mai stato salvato (None).
# Una stringa vuota salvata dall'utente significa invece "nessuno". Chi li
# aveva salvati riceve quelli nuovi dal passo 9 (nazgarr/core/db.py).
DEFAULT_ENABLED_PRESETS = [MEDIA_SERVER_METADATA_PRESET, SYSTEM_FILES_PRESET, TORRENT_FILES_PRESET]


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

