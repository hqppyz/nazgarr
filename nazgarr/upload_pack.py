"""Un pack di file scelti a mano (decisione dell'utente, 2026-10-02): gli
episodi di una serie scaricati uno alla volta, magari ognuno già in seed col
suo torrent, diventano un season pack (o un complete pack) senza spostare
niente. Si scelgono i video dalla libreria o dalla vista dei torrent; i
sottotitoli accanto a un episodio, con il suo stesso nome, entrano da soli.

La sorgente del job non è una cartella ma la lista dei file (pack_json,
percorsi relativi alla radice del disco, ognuno passato da resolve_scoped):
job.source_path è solo la loro cartella comune e nessuno la percorre. Dentro
il pack ogni file è conosciuto per il suo nome (unico), e il torrent nasce
sempre dagli hardlink nella cartella per gli upload: una cartella nuova, con
le sottocartelle "Season 01", "Season 02"... per un complete pack. I torrent
degli episodi restano come sono e seedano gli stessi byte.

Episodi di release diverse (risoluzione, sorgente, codec, gruppo, lingue)
farebbero un pack misto, che il nome non racconta e molti tracker rifiutano:
l'analisi li segnala e l'upload resta bloccato finché l'utente non conferma
(override pack_mixed_confirmed).
"""

import json
import os
import re

from sqlalchemy.orm import Session

from nazgarr import dovi_probe, mediainfo_util, upload_jobs
from nazgarr.file_types import is_video
from nazgarr.fs_scope import resolve_scoped
from nazgarr.guess import clean_name
from nazgarr.guess import guess as guess_name
from nazgarr.models import Disk, UploadJob
from nazgarr.upload_jobs import UploadJobError
from nazgarr.upload_naming import hdr_full

ORIGIN = "pack"
MAX_FILES = 500
SUBTITLE_EXTS = (".srt", ".ass", ".ssa", ".sub", ".idx", ".sup", ".vtt")
# "S01E01", "S01E01E02", "S01E01-E02", "S01E01-02", "1x01".
_EPISODE = re.compile(r"(?i)\bS\d{1,3}[ ._-]?E\d{1,4}(?:-?E\d{1,4}|-\d{1,4})*\b|\b\d{1,2}x\d{2,3}\b")


def is_pack(job: UploadJob) -> bool:
    return bool(job.pack_json)


def _data(job: UploadJob) -> dict:
    return json.loads(job.pack_json or "{}")


def name(job: UploadJob) -> str:
    """Il nome della sorgente: quello del pack, o la cartella/il file."""
    if is_pack(job):
        return _data(job).get("name") or "pack"
    return os.path.basename(job.source_path.rstrip(os.sep))


def entries(job: UploadJob) -> list[tuple[str, str]]:
    """(percorso assoluto, nome dentro il pack) di ogni file del pack, i
    percorsi ricontrollati a ogni uso: dentro il disco, file veri, niente
    symlink in mezzo."""
    disk = job.disk
    if disk is None:
        raise UploadJobError("upload_disk_missing")
    out = []
    for relative in _data(job).get("files", []):
        out.append((_checked(disk, relative), os.path.basename(relative)))
    return out


def _checked(disk: Disk, relative: str) -> str:
    path = resolve_scoped(disk.root_path, relative)
    lexical = os.path.abspath(os.path.join(disk.root_path, relative))
    if os.path.realpath(lexical) != lexical or os.path.islink(lexical):
        # Si pubblicherebbe (e si metterebbe in seed) il file a cui punta il link.
        raise UploadJobError("upload_source_has_symlinks", path=relative)
    if not os.path.isfile(path):
        raise UploadJobError("upload_source_not_found", path=relative)
    return path


def _sidecars(video: str) -> list[str]:
    """I sottotitoli accanto al video con il suo nome ("Ep.mkv" -> "Ep.it.srt")."""
    folder, stem = os.path.dirname(video), os.path.splitext(os.path.basename(video))[0]
    found = []
    for entry in sorted(os.scandir(folder), key=lambda e: e.name):
        if (entry.is_file(follow_symlinks=False) and entry.name.startswith(stem + ".")
                and os.path.splitext(entry.name)[1].lower() in SUBTITLE_EXTS):
            found.append(entry.path)
    return found


def season_name(source: str, seasons: list[int]) -> str:
    """Il nome di un episodio ("Show.S01E01.1080p.WEB-DL-GRP") come nome del
    pack: l'episodio diventa la stagione ("Show.S01.1080p.WEB-DL-GRP"), o
    l'intervallo per un complete pack ("S01-S03")."""
    source = clean_name(source)  # niente "_t00" di MakeMKV nel nome del pack
    stem = os.path.splitext(source)[0] if is_video(source) else source
    if not seasons:
        return stem
    token = f"S{seasons[0]:02d}" if len(seasons) == 1 else f"S{min(seasons):02d}-S{max(seasons):02d}"
    renamed, count = _EPISODE.subn(token, stem, count=1)
    return renamed if count else stem


def _seasons(names: list[str]) -> list[int]:
    seasons = set()
    for file_name in names:
        season = guess_name(file_name).get("season")
        for value in season if isinstance(season, list) else [season]:
            if isinstance(value, int) and 0 <= value < 100:
                seasons.add(value)
    return sorted(seasons)


def create_job(
    session: Session,
    disk: Disk,
    files: list[str],
    tracker_ids: list[int] | None = None,
    forced_ids: dict | None = None,
    overrides: dict | None = None,
    tracker_choices: dict[int, dict] | None = None,
) -> UploadJob:
    """Il job di un pack: almeno due video dello stesso disco, ognuno con un
    nome diverso (dentro il torrent finiscono nella stessa cartella), più i
    loro sottotitoli."""
    videos = list(dict.fromkeys(f.strip().lstrip("/") for f in files if f and f.strip()))
    if len(videos) < 2:
        raise UploadJobError("upload_pack_too_few_files")
    if len(videos) > MAX_FILES:
        raise UploadJobError("upload_pack_too_many_files", max=MAX_FILES)
    root = os.path.realpath(disk.root_path)
    picked: list[str] = []
    for relative in videos:
        path = _checked(disk, relative)
        if not is_video(path):
            raise UploadJobError("upload_pack_not_a_video", path=relative)
        picked.append(path)
        picked.extend(p for p in _sidecars(path) if p not in picked)
    names = [os.path.basename(p) for p in picked]
    duplicate = next((n for n in names if names.count(n) > 1), None)
    if duplicate is not None:
        raise UploadJobError("upload_pack_duplicate_name", name=duplicate)

    common = os.path.commonpath(picked)
    if os.path.isfile(common):
        common = os.path.dirname(common)
    video_names = [os.path.basename(p) for p in picked if is_video(p)]
    pack = {
        "name": season_name(sorted(video_names)[0], _seasons(video_names)),
        "files": [os.path.relpath(p, root) for p in picked],
    }
    return upload_jobs.insert_job(
        session, disk, os.path.relpath(common, root), common, True, tracker_ids, forced_ids, overrides,
        tracker_choices, ORIGIN, pack_json=json.dumps(pack),
    )


# --- pack misti ---------------------------------------------------------------


def _resolution(video: dict) -> str | None:
    width, height = video.get("width") or 0, video.get("height") or 0
    if width >= 3200 or height >= 1800:
        return "2160p"
    if width >= 1700 or height >= 900:
        return "1080p"
    if width >= 1100 or height >= 650:
        return "720p"
    return "SD" if width or height else None


def signature(path: str, summary: dict | None) -> dict:
    """Quello che deve essere uguale in tutti gli episodi di un pack."""
    guess = guess_name(os.path.basename(path))
    video = (summary or {}).get("video") or {}
    audio = (summary or {}).get("audio") or []
    return {
        "resolution": _resolution(video),
        "video_codec": video.get("format"),
        # Normalizzato come nei nomi ("DV.P8.HDR10"): lo stesso HDR scritto in
        # modo diverso (es. il DV letto dal flusso) non fa un pack misto.
        "hdr": hdr_full(video) if video else None,
        "audio_codec": (audio[0].get("commercial_name") or audio[0].get("format")) if audio else None,
        "audio_languages": ", ".join(sorted({a.get("language") or "?" for a in audio})) or None,
        "source": str(guess.get("source")) if guess.get("source") else None,
        "group": guess.get("release_group"),
    }


def mixed(job: UploadJob) -> dict[str, list[str]]:
    """I campi che cambiano fra gli episodi del pack, con i valori trovati.
    Un valore che manca (es. il gruppo non scritto nel nome di un file della
    libreria) non conta: solo valori diversi."""
    values: dict[str, set[str]] = {}
    for path, _name in entries(job):
        if not is_video(path):
            continue
        summary = mediainfo_util.extract_summary(path)
        dovi_probe.complete(summary, path)  # un episodio senza dvcC non è un pack misto
        for field, value in signature(path, summary).items():
            if value is not None:
                values.setdefault(field, set()).add(str(value))
    return {field: sorted(found) for field, found in values.items() if len(found) > 1}
