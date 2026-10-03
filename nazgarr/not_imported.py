"""Torrent in seed senza alcun hardlink in libreria ("not imported", lo stato
"ignored" per file) e PERCHÉ sono lì. Sola lettura: nessun file e nessun
torrent viene toccato; le azioni (es. rimuovere dal client i vecchi upgrade)
sono un passo futuro, da far passare dalla coda di approvazione.

Si ragiona per torrent, non per file: i file extra (nfo, sample) seguono il
loro torrent. La categoria viene dal video principale (il più grande):

- superseded: Radarr/Sonarr l'avevano importato (evento di import: file del
  download -> contenuto), ma in libreria quel contenuto ha ora un altro file
  (un upgrade). Senza history, stesso titolo/anno (film) o serie+episodio
  riconosciuti dal nome;
- copy: lo stesso contenuto è in libreria come copia su un altro inode
  (stessa dimensione e impronta veloce, o il file importato è ancora lì):
  spazio occupato due volte;
- removed: importato in passato, ma il contenuto non è più in libreria;
- never_imported: nessun import noto (rifiutato, download manuale,
  cross-seed) o Radarr/Sonarr non configurati;
- extras_only: nessun video nel torrent.

Ricalcolata a fine scansione, solo con dati affidabili (scan e
indicizzazione riusciti, come nazgarr/file_changes.py).
"""

import json
import logging
import os
import re
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from nazgarr.db_utils import bulk_insert
from nazgarr.duplicates import compute_fast_hash
from nazgarr.exclusions import load_exclusions
from nazgarr.file_types import is_video
from nazgarr.guess import guess as guess_name
from nazgarr.hardlinks import media_links
from nazgarr.models import (
    ClientTorrent,
    ClientTorrentFile,
    Disk,
    MediaFile,
    MediaItem,
    NotImportedTorrent,
    RunLog,
    SeedFile,
)
from nazgarr.scan_state import is_current, latest_scan_by_disk
from nazgarr.settings_repo import get_setting, set_setting

logger = logging.getLogger(__name__)

CATEGORIES = ("superseded", "copy", "removed", "never_imported", "extras_only")


def _norm(title: str | None) -> str:
    text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


class _Library:
    """I file correnti della libreria, indicizzati per quello che serve qui."""

    def __init__(self, session: Session):
        exclusions = load_exclusions(session)
        latest = latest_scan_by_disk(session, MediaFile)
        items = {i.id: i for i in session.query(MediaItem).all()}
        self.by_content: dict[tuple, list[MediaFile]] = defaultdict(list)
        self.by_size: dict[int, list[MediaFile]] = defaultdict(list)
        self.by_path_key: dict[tuple[str, int], MediaFile] = {}
        self.movies_by_title: dict[tuple[str, int | None], tuple] = {}
        self.series_by_title: dict[str, int] = {}
        from nazgarr.arr import path_key  # import qui: app.arr importa modelli e httpx

        for mf in session.query(MediaFile).all():
            if not is_current(mf, latest) or not is_video(mf.relative_path) or exclusions.is_excluded(mf.relative_path):
                continue
            self.by_size[mf.size_bytes].append(mf)
            self.by_path_key[(path_key(mf.relative_path), mf.size_bytes)] = mf
            item = items.get(mf.media_item_id) if mf.media_item_id else None
            if item is None:
                continue
            key = (item.content_type, item.tmdb_id, item.season_number, item.episode_number)
            self.by_content[key].append(mf)
            if item.content_type == "movie":
                self.movies_by_title[(_norm(item.title), item.year)] = key
                self.movies_by_title.setdefault((_norm(item.title), None), key)
            elif item.title:
                self.series_by_title[_norm(item.title)] = item.tmdb_id

    def replacement(self, content: tuple) -> MediaFile | None:
        files = self.by_content.get(content)
        return max(files, key=lambda f: f.size_bytes) if files else None


def _by_name(library: _Library, name: str) -> tuple | None:
    """Il contenuto in libreria con lo stesso titolo (e anno) o serie+episodio."""
    guess = guess_name(os.path.basename(name))
    title = guess.get("title")
    if not title:
        return None
    if guess.get("type") == "episode":
        tmdb_id = library.series_by_title.get(_norm(title))
        season, episode = guess.get("season"), guess.get("episode")
        if tmdb_id is None or not isinstance(season, int) or not isinstance(episode, int):
            return None
        return ("tv", tmdb_id, season, episode)
    return library.movies_by_title.get((_norm(title), guess.get("year")))


def _classify_torrent(library: _Library, arr_index, main_abs: str, main_size: int, main_name: str):
    """(categoria, dettaglio, matched_by, contenuto, file sostitutivo)."""
    # Stesso contenuto già in libreria come copia su un altro inode.
    for mf in library.by_size.get(main_size, []):
        if mf.content_hash and compute_fast_hash(main_abs) == mf.content_hash:
            return "copy", "The same file is in the library as a copy, not a hardlink", "hash", None, mf

    if arr_index is not None:
        imported = arr_index.imported_for(main_abs, main_size)
        content = arr_index.imported_content_for(main_abs, main_size)
        if imported is not None:
            still_there = library.by_path_key.get(imported)
            if still_there is not None:
                return "copy", "Imported as a copy instead of a hardlink", "arr", content, still_there
            replacement = library.replacement(content) if content else None
            if replacement is not None:
                detail = "Imported, then replaced in the library by another file"
                return "superseded", detail, "arr", content, replacement
            return "removed", "Imported in the past, no longer in the library", "arr", content, None

    content = _by_name(library, main_name)
    replacement = library.replacement(content) if content else None
    if replacement is not None:
        detail = "Same title in the library with another file (matched by name)"
        return "superseded", detail, "name", content, replacement
    if arr_index is None:
        return "never_imported", "Radarr/Sonarr not configured: no import history to tell why", None, content, None
    return "never_imported", "Radarr/Sonarr have no record of importing it", None, content, None


STATUS_SETTING = "not_imported_status"


def _save_status(session: Session, **status) -> None:
    """Quando è stata calcolata l'ultima volta, o perché l'ultima scansione
    l'ha saltata: la vista lo mostra invece di restare vuota senza motivo."""
    previous = load_status(session)
    set_setting(session, STATUS_SETTING, json.dumps({**previous, **status}, default=str))


def load_status(session: Session) -> dict:
    try:
        return json.loads(get_setting(session, STATUS_SETTING) or "{}")
    except ValueError:
        return {}


def mark_skipped(session: Session, reason: str) -> None:
    _save_status(session, skipped_at=datetime.now(UTC).isoformat(), skipped_reason=reason)


def classify_not_imported(session: Session, arr_index, run: RunLog | None = None) -> dict[str, int]:
    library = _Library(session)
    exclusions = load_exclusions(session)
    linked_seed_ids = {sf_id for sfs in media_links(session).values() for sf_id, _ in sfs}
    latest_seed = latest_scan_by_disk(session, SeedFile)
    seeds = {sf.id: sf for sf in session.query(SeedFile).all() if is_current(sf, latest_seed)}
    disks = {d.id: d for d in session.query(Disk).all()}

    files_by_torrent: dict[int, list[ClientTorrentFile]] = defaultdict(list)
    for ctf in session.query(ClientTorrentFile).all():
        files_by_torrent[ctf.client_torrent_id].append(ctf)

    rows = []
    counts = dict.fromkeys(CATEGORIES, 0)
    for torrent in session.query(ClientTorrent).all():
        files = files_by_torrent.get(torrent.id, [])
        on_disk = [f for f in files if f.seed_file_id in seeds]
        # Nessun file sui dischi scansionati: non sappiamo dov'è, niente da dire.
        # Almeno un file hardlinkato: il torrent è importato (anche se a metà).
        if not on_disk or any(f.seed_file_id in linked_seed_ids for f in on_disk):
            continue
        videos = [f for f in on_disk if is_video(f.path_in_torrent)]
        total = sum(f.size_bytes or 0 for f in files)
        video_bytes = sum(f.size_bytes or 0 for f in videos)
        if not videos:
            category, detail, matched_by, content, replacement, main = (
                "extras_only", "No video in this torrent", None, None, None, None
            )
        else:
            main = max(videos, key=lambda f: f.size_bytes or 0)
            seed = seeds[main.seed_file_id]
            main_abs = os.path.join(disks[seed.disk_id].root_path, seed.relative_path)
            category, detail, matched_by, content, replacement = _classify_torrent(
                library, arr_index, main_abs, seed.size_bytes, main.path_in_torrent
            )
        if main is not None:
            excluded = exclusions.is_excluded(seeds[main.seed_file_id].relative_path)
        else:
            excluded = all(exclusions.is_excluded(seeds[f.seed_file_id].relative_path) for f in on_disk)
        if not excluded:
            counts[category] += 1
        rows.append({
            "client_torrent_id": torrent.id, "category": category, "detail": detail, "matched_by": matched_by,
            "content_type": content[0] if content else None, "tmdb_id": content[1] if content else None,
            "season_number": content[2] if content else None, "episode_number": content[3] if content else None,
            "main_path": main.path_in_torrent if main else None,
            "replaced_by_media_file_id": replacement.id if replacement else None,
            "total_bytes": total, "video_bytes": video_bytes, "file_count": len(files),
            "excluded": excluded, "run_id": run.id if run else None,
        })

    session.query(NotImportedTorrent).delete(synchronize_session=False)
    bulk_insert(session, NotImportedTorrent.__table__, rows)
    session.commit()
    _save_status(session, computed_at=datetime.now(UTC).isoformat(), with_arr=arr_index is not None,
                 skipped_at=None, skipped_reason=None)
    logger.info("Not imported: %d torrent (%s)", len(rows), ", ".join(f"{k} {v}" for k, v in counts.items() if v))
    return counts
