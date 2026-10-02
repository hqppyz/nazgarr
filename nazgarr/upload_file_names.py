"""Nomi dei file dentro il torrent di un upload (decisione dell'utente,
2026-10-01). Partendo da un file della libreria, il nome è quello di
Plex/Radarr/Sonarr ("Dune Part Two (2024) {imdb-...}.mkv"), non un nome di
release. Tre modalità, una per job (il torrent è uno, uguale per tutti i
tracker):

- "hardlink": i percorsi del torrent che già seeda gli stessi byte su un
  client (se tutti i video della sorgente sono hardlink di uno stesso
  torrent). È il nome della release originale, di solito il migliore.
- "generated": un nome a punti dal pattern in Settings > Upload (le stesse
  variabili dei nomi per tracker), es.
  Dune.Part.Two.2024.2160p.BluRay.REMUX.DV.HDR.TrueHD.7.1.Atmos.ITA.ENG.HEVC-GRP;
  nei pack, un nome per cartella e uno per ogni episodio.
- "original": i nomi della sorgente, come prima.

Di default "hardlink" se c'è, se no "generated".

Il piano è una cartella (o un file) e, per ogni file della sorgente, il
percorso che avrà dentro il torrent. Con nomi diversi dall'originale,
nazgarr/upload_execute.py crea gli hardlink con quei nomi nella cartella di seed
e calcola gli hash da lì.
"""

import fnmatch
import json
import os
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

from nazgarr import settings_repo
from nazgarr.file_types import is_video
from nazgarr.models import ClientTorrent, ClientTorrentFile, SeedFile, UploadJob
from nazgarr.upload_naming import build_name, detect_with_fallback, release_values

MODES = ("hardlink", "generated", "original")
SETTING = "upload_file_naming_rules"
# Come in nazgarr/upload_execute.py (torf): mai nel torrent.
EXCLUDE_GLOBS = [".*", "*.part", "*.!qB", "*.!ut", "Thumbs.db", "desktop.ini", "*sample*", "*Sample*"]

_MOVIE = ("{title} {year} {edition} {repack} {resolution} {source_full} {hybrid} {type} {audio} "
          "{audio_languages} {subs} {hdr} {video_codec} {group}")
_TV = ("{title} {season} {edition} {repack} {resolution} {source_full} {hybrid} {type} {audio} "
       "{audio_languages} {subs} {hdr} {video_codec} {group}")
DEFAULT_RULES = {
    "templates": {"default": _MOVIE, "tv": _TV},
    "title": "original",
    "separator": ".",
    "group_separator": "-",
    # Lingue audio nel nome, MULTI da 4 in su; dei sottotitoli solo "SUBS"
    # se ci sono (decisione dell'utente, 2026-10-01).
    "audio_languages": {"style": "all", "multi_from": 4},
    "subs_format": "SUBS",
    # I codec come nelle release scene (DDP, non DD+).
    "audio_codecs": {"E-AC-3": "DDP", "AC-3": "DD"},
    # La sorgente la dice {source_full}: il tipo solo dove aggiunge qualcosa.
    "type_labels": {"REMUX": "REMUX", "WEBDL": "WEB-DL", "WEBRIP": "WEBRip", "WEBMUX": "WEBMux",
                    "DLMUX": "DLMux", "ENCODE": "", "HDTV": "", "DVDRIP": "DVDRip", "BRRIP": "BRRip", "DISC": ""},
}


def rules(session: Session) -> dict:
    raw = settings_repo.get_setting(session, SETTING)
    try:
        return json.loads(raw) if raw else DEFAULT_RULES
    except ValueError:
        return DEFAULT_RULES


def sanitize(name: str) -> str:
    """Un nome da file come nelle release: niente accenti, niente segni
    (":" "'" "," ...), "&" diventa "and", un solo punto alla volta."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = text.replace("&", "and").replace("'", "").replace("`", "")
    text = re.sub(r"[^A-Za-z0-9.+\-]+", ".", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"\.?-\.?", "-", text)  # niente punti attaccati al trattino del gruppo
    return text.strip(".-")


@dataclass
class FilePlan:
    mode: str
    content_name: str  # la cartella del torrent, o il file se è uno solo
    files: list[tuple[str, str]]  # (file della sorgente, percorso dentro il torrent)
    # Un file solo tolto dalla sua cartella (single_file): il torrent è il
    # file, e folder la cartella (relativa a quella di seed) in cui seeda, se
    # resta; None, direttamente nella cartella di seed.
    single_file: bool = False
    folder: str | None = None

    @property
    def renamed(self) -> bool:
        return self.mode != "original"


def _excluded(relative: str) -> bool:
    parts = relative.replace("\\", "/").split("/")
    return any(fnmatch.fnmatch(part, glob) for part in parts for glob in EXCLUDE_GLOBS)


def _source_files(job: UploadJob) -> list[tuple[str, str]]:
    """(percorso assoluto, relativo alla sorgente) dei file che vanno nel torrent."""
    if not job.is_dir:
        return [(job.source_path, os.path.basename(job.source_path))]
    out = []
    for dirpath, dirnames, filenames in os.walk(job.source_path):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            relative = os.path.relpath(path, job.source_path)
            if os.path.isfile(path) and not os.path.islink(path) and not _excluded(relative):
                out.append((path, relative))
    return out


def _original(job: UploadJob, files: list[tuple[str, str]]) -> FilePlan:
    name = os.path.basename(job.source_path.rstrip(os.sep))
    if not job.is_dir:
        return FilePlan("original", name, [(files[0][0], name)])
    return FilePlan("original", name, [(path, f"{name}/{relative}") for path, relative in files])


def _hardlink(session: Session, job: UploadJob, files: list[tuple[str, str]]) -> FilePlan | None:
    """I percorsi del torrent di un client che ha in hardlink tutti i video
    della sorgente, se ce n'è uno."""
    paths: dict[str, dict[int, str]] = {}
    for path, _relative in files:
        try:
            st = os.stat(path)
        except OSError:
            continue
        rows = (
            session.query(ClientTorrentFile.client_torrent_id, ClientTorrentFile.path_in_torrent)
            .join(SeedFile, SeedFile.id == ClientTorrentFile.seed_file_id)
            .filter(SeedFile.st_dev == st.st_dev, SeedFile.inode == st.st_ino)
            .all()
        )
        paths[path] = {torrent_id: in_torrent for torrent_id, in_torrent in rows}
    videos = [path for path, relative in files if is_video(relative)]
    common = set.intersection(*(set(paths.get(v, {})) for v in videos)) if videos else set()
    if not common:
        return None
    torrent = session.get(ClientTorrent, min(common))
    planned = []
    for path, relative in files:
        in_torrent = paths.get(path, {}).get(torrent.id)
        if in_torrent is None:
            continue  # un file che quel torrent non ha (un nfo nostro): resta fuori
        planned.append((path, in_torrent.replace("\\", "/")))
    if not planned:
        return None
    roots = {p.split("/", 1)[0] for _s, p in planned}
    if len(roots) == 1:
        # Una cartella comune ("Release/file.mkv"), o un torrent di un file solo.
        return FilePlan("hardlink", roots.pop(), planned)
    # File sparsi senza cartella comune: sotto il nome del torrent.
    return FilePlan("hardlink", torrent.name, [(s, f"{torrent.name}/{p}") for s, p in planned])


def _generated(session: Session, job: UploadJob, files: list[tuple[str, str]], mediainfo: dict | None,
               overrides: dict, detected: dict) -> FilePlan:
    rules_ = rules(session)
    base_values = release_values(job, detected, mediainfo, overrides, rules_)
    base = sanitize(build_name(rules_, base_values))
    if not job.title or not base:
        # Senza un titolo (nessun match TMDB) non c'è un nome da costruire:
        # meglio i nomi della sorgente che un ".mkv".
        return _original(job, files)
    main_ext = os.path.splitext(max(files, key=lambda f: os.path.getsize(f[0]))[0])[1].lower()
    if not job.is_dir:
        return FilePlan("generated", base + main_ext, [(files[0][0], base + main_ext)])

    layout = json.loads(job.layout_json or "{}")
    episodes = {
        v.get("relative_path"): (v.get("season"), (v.get("episodes") or [None])[0])
        for v in layout.get("videos", [])
    }
    planned = []
    renamed: dict[str, str] = {}  # stem del video originale -> stem nuovo, per i suoi sottotitoli
    videos = [(p, r) for p, r in files if is_video(r)]
    for path, relative in files:
        if not is_video(relative):
            continue
        ext = os.path.splitext(relative)[1].lower()
        season, episode = episodes.get(relative, (None, None))
        if job.content_type == "tv" and episode is not None:
            one = _EpisodeJob(job, season, episode)
            name = sanitize(build_name(rules_, release_values(one, detected, mediainfo, overrides, rules_)))
        elif len(videos) == 1:
            name = base
        else:
            name = sanitize(os.path.splitext(os.path.basename(relative))[0])
        renamed[os.path.splitext(os.path.basename(relative))[0]] = name
        planned.append((path, f"{base}/{name}{ext}"))
    # Gli altri file nella cartella del torrent: un sottotitolo
    # ("Show - S01E01 - Pilot.it.srt") segue il suo episodio, il resto (nfo,
    # immagini) tiene il suo nome. Niente sottocartelle "Season 01".
    taken = {target for _s, target in planned}
    for path, relative in files:
        if is_video(relative):
            continue
        filename = os.path.basename(relative)
        stem = next((old for old in sorted(renamed, key=len, reverse=True) if filename.startswith(old)), None)
        target = f"{base}/{renamed[stem]}{filename[len(stem):]}" if stem else f"{base}/{filename}"
        if target in taken:  # due file con lo stesso nome in sottocartelle diverse
            target = f"{base}/{relative}"
        taken.add(target)
        planned.append((path, target))
    return FilePlan("generated", base, planned)


class _EpisodeJob:
    """Il job visto come un solo episodio: stagione ed episodio nel nome."""

    def __init__(self, job: UploadJob, season: int | None, episode: int):
        self._job = job
        self.kind = "episode"
        self.episode = episode
        self.seasons_json = json.dumps([season] if season is not None else json.loads(job.seasons_json or "[]")[:1])

    def __getattr__(self, name):
        return getattr(self._job, name)


def available_modes(session: Session, job: UploadJob) -> list[str]:
    files = _source_files(job)
    return [m for m in MODES if m != "hardlink" or _hardlink(session, job, files) is not None]


def _in_media_library(job: UploadJob) -> bool:
    disk = getattr(job, "disk", None)
    if disk is None or not disk.media_rel_path:
        return False
    media = os.path.realpath(os.path.join(disk.root_path, disk.media_rel_path))
    return os.path.realpath(job.source_path).startswith(media + os.sep)


AUTO_RENAME_SETTING = "upload_auto_rename"


def auto_rename(session: Session) -> bool:
    """Rinominare in automatico (Settings › Releases), acceso di default:
    spento, ogni upload parte con i nomi originali, e gli altri restano da
    scegliere a mano."""
    return (settings_repo.get_setting(session, AUTO_RENAME_SETTING) or "true").lower() != "false"


def default_mode(session: Session, job: UploadJob) -> str:
    """Il nome del torrent in hardlink se c'è; se no un nome generato, per un
    file della libreria (nomi alla Plex) o una release della cartella
    osservata (la tua, da chiamare come vuole il pattern). Una sorgente già
    nella cartella dei torrent ha già il suo nome di release, e lo tiene.
    Con il rename automatico spento, sempre i nomi originali."""
    if not auto_rename(session):
        return "original"
    if "hardlink" in available_modes(session, job):
        return "hardlink"
    return "generated" if _in_media_library(job) or job.origin == "watch" else "original"


SINGLE_FILE_SETTING = "upload_single_file"
SINGLE_FILE_FOLDER_SETTING = "upload_single_file_folder"
FOLDER_CHOICES = ("keep", "remove")


def single_file_folder(session: Session) -> str | None:
    """Con l'impostazione accesa (Settings › Releases, spenta di default),
    "keep" o "remove": cosa fare della cartella che conteneva il file."""
    if (settings_repo.get_setting(session, SINGLE_FILE_SETTING) or "").lower() != "true":
        return None
    choice = (settings_repo.get_setting(session, SINGLE_FILE_FOLDER_SETTING) or "keep").lower()
    return choice if choice in FOLDER_CHOICES else "keep"


def _as_single_file(found: FilePlan, folder_choice: str | None) -> FilePlan:
    """Una cartella con un file solo dentro il torrent (decisione
    dell'utente, 2026-10-02): il torrent diventa quel file, senza cartella.
    Conta quello che entra nel torrent: un sample o un Thumbs.db non ne
    fanno parte, un nfo sì (e la cartella resta). La cartella può restare
    come cartella di seed (il client punta lì dentro) o sparire: il file
    seeda direttamente nella cartella di seed."""
    if folder_choice is None or len(found.files) != 1 or "/" not in found.files[0][1]:
        return found
    source, target = found.files[0]
    folder, name = target.rsplit("/", 1)
    return FilePlan(found.mode, name, [(source, name)], single_file=True,
                    folder=folder if folder_choice == "keep" else None)


def plan(session: Session, job: UploadJob, mode: str | None = None) -> FilePlan:
    """Il piano dei nomi per la modalità scelta (o quella di default), un
    file solo senza la sua cartella se l'impostazione è accesa."""
    return _as_single_file(_plan(session, job, mode), single_file_folder(session))


def _plan(session: Session, job: UploadJob, mode: str | None) -> FilePlan:
    files = _source_files(job)
    analysis = json.loads(job.analysis_json or "{}")
    overrides = json.loads(job.overrides_json or "{}")
    mode = mode or overrides.get("file_naming") or default_mode(session, job)
    if mode == "hardlink":
        found = _hardlink(session, job, files)
        if found is not None:
            return found
        mode = "generated"
    if mode == "generated" and files:
        name_source = analysis.get("name_source") or {}
        detected = detect_with_fallback(name_source.get("name") or os.path.basename(job.source_path),
                                        name_source.get("fallback"))
        return _generated(session, job, files, analysis.get("mediainfo"), overrides, detected)
    return _original(job, files)
