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

Lo stesso pack nasce da solo da una cartella con più stagioni quando al
match se ne sceglie solo una parte (season_selection).
"""

import json
import os
import re

from sqlalchemy.orm import Session

from nazgarr.core.file_types import is_video
from nazgarr.core.fs_scope import resolve_scoped
from nazgarr.core.models import Disk, UploadJob
from nazgarr.library import episode_orders
from nazgarr.library import mediainfo as mediainfo_util
from nazgarr.library.guess import clean_name
from nazgarr.library.guess import guess as guess_name
from nazgarr.upload import dovi_probe
from nazgarr.upload import jobs as upload_jobs
from nazgarr.upload.jobs import UploadJobError
from nazgarr.upload.naming import hdr_full, mi_resolution

ORIGIN = "pack"
MAX_FILES = 500
SUBTITLE_EXTS = (".srt", ".ass", ".ssa", ".sub", ".idx", ".sup", ".vtt")
# "S01E01", "S01E01E02", "S01E01-E02", "S01E01-02", "1x01".
_EPISODE = re.compile(r"(?i)\bS\d{1,3}[ ._-]?E\d{1,4}(?:-?E\d{1,4}|-\d{1,4})*\b|\b\d{1,2}x\d{2,3}\b")
# Le stagioni nel nome di una cartella: "S01", "S01-S03", "S01-03".
_SEASONS = re.compile(r"(?i)\bS\d{1,3}(?:-S?\d{1,3})?\b")


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
    renamed, count = _EPISODE.subn(_token(seasons), stem, count=1)
    return renamed if count else stem


def _token(seasons: list[int]) -> str:
    return f"S{seasons[0]:02d}" if len(seasons) == 1 else f"S{min(seasons):02d}-S{max(seasons):02d}"


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
    picked = _pick(disk, videos)
    common = _common_folder(picked)
    video_names = [os.path.basename(p) for p in picked if is_video(p)]
    pack = {
        "name": season_name(sorted(video_names)[0], _seasons(video_names)),
        "files": [os.path.relpath(p, root) for p in picked],
    }
    return upload_jobs.insert_job(
        session, disk, os.path.relpath(common, root), common, True, tracker_ids, forced_ids, overrides,
        tracker_choices, ORIGIN, pack_json=json.dumps(pack),
    )


def _pick(disk: Disk, videos: list[str]) -> list[str]:
    """I video (relativi al disco) con i loro sottotitoli, percorsi
    controllati. Nel pack stanno tutti nella stessa cartella: mai due file
    con lo stesso nome."""
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
    return picked


def _common_folder(paths: list[str]) -> str:
    common = os.path.commonpath(paths)
    return os.path.dirname(common) if os.path.isfile(common) else common


# --- le stagioni scelte di una cartella con più stagioni ----------------------


def _video_seasons(video: dict, translated: dict[int, dict[int, set[int]]] | None) -> set[int]:
    """Le stagioni di un video della sorgente nella numerazione scelta al
    match (translated: episodio dei file -> stagioni scelte, per stagione
    dei file; None se i file seguono l'ordinamento scelto). Un episodio che
    non si traduce prende le stagioni degli episodi vicini della stessa
    stagione dei file (audit 2026-10-18: con quella dei file, il video
    finiva fuori dal season pack in cui stanno i suoi vicini, perso
    dall'upload)."""
    season = video.get("season")
    if season is None:
        return set()
    episodes = video.get("episodes") or []
    if translated is None or not episodes:
        return {season}
    known = translated.get(season, {})
    out: set[int] = set()
    for e in episodes:
        if e in known:
            out |= known[e]
            continue
        lower = max((k for k in known if k < e), default=None)
        higher = min((k for k in known if k > e), default=None)
        out |= (known.get(lower, set()) | known.get(higher, set())) or {season}
    return out


def _with_seasons(job: UploadJob, order_snapshot: dict | None) -> list[tuple[dict, set[int]]]:
    """Ogni video della sorgente con le sue stagioni nella numerazione scelta."""
    snapshot = order_snapshot or {}
    layout = json.loads(job.layout_json or "{}")
    videos = layout.get("videos") or []
    translated = None
    if snapshot.get("chosen") and snapshot.get("files"):
        lookup = episode_orders.translator(episode_orders.EpisodeOrder.from_dict(snapshot["files"]),
                                           episode_orders.EpisodeOrder.from_dict(snapshot["chosen"]))
        translated = {}
        for video in videos:
            season = video.get("season")
            for e in video.get("episodes") or [] if season is not None else []:
                refs = lookup(season, e)
                if refs:
                    translated.setdefault(season, {})[e] = {s for s, _e in refs}
    return [(video, _video_seasons(video, translated)) for video in videos]


def seasons_in_source(job: UploadJob) -> set[int]:
    """Le stagioni con almeno un video nella sorgente di un job confermato,
    nella numerazione scelta al match."""
    found = _with_seasons(job, json.loads(job.episode_order_json or "null"))
    return set().union(*(found_seasons for _video, found_seasons in found))


def season_selection(job: UploadJob, kind: str, seasons: list[int], order_snapshot: dict | None) -> dict:
    """Una cartella con più stagioni di cui al match se ne sceglie solo una
    parte (segnalato 2026-10-11: dalla cartella osservata arriva la serie
    intera, e il season pack della S01 conteneva tutti gli episodi): l'upload
    prende solo i video di quelle stagioni, che stiano nella loro
    sottocartella ("Season 01/") o tutti insieme ("S01E01..."), e diventa un
    pack come quelli scelti a mano, con i loro sottotitoli. Il resto (nfo,
    altre stagioni, video senza stagione nel nome o nella cartella) resta
    fuori.

    I valori del job da cambiare alla conferma del match; vuoto se la
    sorgente va bene com'è: tutte le sue stagioni scelte, o nessuna (l'utente
    rinumera: i file dicono S01, la serie su TMDB S03). La cartella di
    partenza resta nel pack (from_folder) per tornare al match."""
    if kind not in ("season_pack", "complete_pack") or not job.is_dir or is_pack(job) or job.disk is None:
        return {}
    layout = json.loads(job.layout_json or "{}")
    wanted = set(seasons)
    found = _with_seasons(job, order_snapshot)
    present = set().union(*(found_seasons for _video, found_seasons in found))
    if not present & wanted or present <= wanted:
        return {}
    kept = [video for video, found_seasons in found if found_seasons & wanted]

    disk = job.disk
    root = os.path.realpath(disk.root_path)
    paths = {video["relative_path"]: os.path.join(job.source_path, video["relative_path"]) for video in kept}
    picked = _pick(disk, [os.path.relpath(path, root) for path in paths.values()])
    common = _common_folder(picked)
    # Il layout dei soli video scelti, con i nomi nel pack: le stagioni lette
    # dalle sottocartelle ("Season 02/03.mkv") restano quelle della cartella.
    videos = [{**video, "relative_path": os.path.basename(video["relative_path"])} for video in kept]
    by_season: dict[int, set[int]] = {}
    for video in videos:
        if video.get("season") is not None:
            by_season.setdefault(video["season"], set()).update(video.get("episodes") or [])
    file_seasons = sorted(by_season)
    main = max(kept, key=lambda video: video.get("size_bytes") or 0)
    selected = {
        **layout,
        "kind": "complete_pack" if len(file_seasons) > 1 else "season_pack",
        "videos": videos,
        "other_files": len(picked) - len(videos),
        "total_size_bytes": sum(video.get("size_bytes") or 0 for video in videos),
        "main_video": paths[main["relative_path"]],
        "seasons": file_seasons,
        "episodes_by_season": {season: sorted(eps) for season, eps in sorted(by_season.items())},
    }
    first = sorted(video["relative_path"] for video in videos)[0]
    name = season_name(first, file_seasons)
    if not _EPISODE.search(clean_name(first)) and file_seasons:
        # Episodi senza "S01E01" nel nome ("Season 03/01.mkv"): il nome della
        # cartella con le stagioni scelte ("Show.S01-S03..." -> "Show.S03...").
        folder_name = os.path.basename(job.source_path.rstrip(os.sep))
        name = _SEASONS.sub(_token(file_seasons), folder_name, count=1)
    pack = {
        "name": name,
        "files": [os.path.relpath(p, root) for p in picked],
        "from_folder": {"relative_path": job.relative_path, "source_path": job.source_path, "layout": layout},
    }
    return {
        "pack_json": json.dumps(pack),
        "relative_path": os.path.relpath(common, root),
        "source_path": common,
        "layout_json": json.dumps(selected),
    }


def from_folder(job: UploadJob) -> dict | None:
    """La cartella da cui è nato un pack di season_selection: relative_path,
    source_path e il suo layout. None per gli altri job."""
    return _data(job).get("from_folder") if is_pack(job) else None


def folder_values(job: UploadJob) -> dict:
    """I valori che riportano un pack di season_selection alla sua cartella
    (di nuovo al match, dove si può scegliere un'altra stagione); vuoto per
    gli altri job."""
    folder = from_folder(job)
    if folder is None:
        return {}
    return {"pack_json": None, "relative_path": folder["relative_path"], "source_path": folder["source_path"],
            "layout_json": json.dumps(folder["layout"])}


# --- pack misti ---------------------------------------------------------------


def signature(path: str, summary: dict | None) -> dict:
    """Quello che deve essere uguale in tutti gli episodi di un pack."""
    guess = guess_name(os.path.basename(path))
    video = (summary or {}).get("video") or {}
    audio = (summary or {}).get("audio") or []
    return {
        "resolution": mi_resolution(video),  # le stesse soglie del nome della release
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
