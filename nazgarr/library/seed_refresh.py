"""Dopo un recheck riuscito: rende subito visibile il nuovo seed, senza
aspettare scan e indicizzazione della run successiva.

Uno stato "seeding" richiede un seed_file (lato torrent) collegato al
media_file e tracciato da un client. Un seed appena ricreato non ha né
l'uno né l'altro finché una run non riscansiona il disco e reindicizza il
client: gli episodi di un pack restavano "orphaned" anche col torrent già
in seed. Qui si registrano i soli file di quel torrent:
- gli hardlink appena creati dall'executor (libreria -> torrent), con
  last_scan_id dell'ultimo scan del disco, così contano come presenti;
- i file di quel solo torrent nel client, collegati per path come fa
  l'indicizzazione completa (nazgarr/torrents/indexer.py).
"""

import json
import logging
import os
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from nazgarr.adapters.torrent_client.base import TorrentClientAdapter
from nazgarr.core.db_utils import bulk_upsert
from nazgarr.core.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.core.models import MediaFile, RunLog, SeedFile, SeedJob, TorrentClient
from nazgarr.library.scan_state import latest_scan_by_disk
from nazgarr.torrents.indexer import store_client_torrents

logger = logging.getLogger(__name__)


def _hardlink_paths(seed_job: SeedJob, mf: MediaFile) -> list[tuple[str, int | None]]:
    """(percorso relativo al disco, media_file_id) di ogni file del torrent
    nella cartella dei nuovi hardlink — gli stessi percorsi dell'executor."""
    candidate = seed_job.candidate
    base = mf.disk.effective_new_torrent_rel_path or ""

    def rel(torrent_path: str) -> str:
        return os.path.normpath(os.path.join(base, candidate.folder or "", torrent_path))

    if candidate.files:
        return [(rel(f.torrent_path), f.media_file_id) for f in candidate.files]
    names = json.loads(candidate.file_list_json) if candidate.file_list_json else []
    return [(rel(names[0] if names else os.path.basename(mf.relative_path)), mf.id)]


def _register_hardlinks(session: Session, seed_job: SeedJob, scan_id: int) -> int:
    mf = session.get(MediaFile, seed_job.source_media_file_id) if seed_job.source_media_file_id else None
    if mf is None:
        return 0
    disk = mf.disk
    scan_id = latest_scan_by_disk(session, SeedFile).get(disk.id) or scan_id
    now = datetime.now(UTC)
    rows = []
    for relative_path, media_file_id in _hardlink_paths(seed_job, mf):
        try:
            # Cartella e nomi vengono dal tracker: mai fuori dal disco.
            st = os.stat(resolve_scoped(disk.root_path, relative_path))
        except (OSError, ScopeViolation):
            continue  # extra non ancora scaricato dal client: lo vedrà il prossimo scan
        rows.append({
            "disk_id": disk.id, "relative_path": relative_path, "size_bytes": st.st_size,
            "st_dev": st.st_dev, "inode": st.st_ino, "media_file_id": media_file_id,
            "last_scan_id": scan_id, "last_seen_at": now,
        })
    bulk_upsert(
        session, SeedFile.__table__, rows, conflict_cols=["disk_id", "relative_path"],
        update_cols=["size_bytes", "st_dev", "inode", "media_file_id", "last_scan_id", "last_seen_at"],
    )
    session.commit()
    return len(rows)


def refresh_seeded_torrent(
    session: Session, seed_job: SeedJob, adapter: TorrentClientAdapter, torrent_client_id: int | None
) -> dict[str, int]:
    scan_id = session.query(func.max(RunLog.id)).scalar()
    if scan_id is None:
        return {"seed_files": 0, "client_files": 0}
    seed_files = 0
    if seed_job.candidate.direction == "media_to_torrent":
        seed_files = _register_hardlinks(session, seed_job, scan_id)
    client_files = 0
    torrent_client = session.get(TorrentClient, torrent_client_id) if torrent_client_id else None
    info = adapter.get_torrent_info(seed_job.info_hash) if torrent_client is not None and seed_job.info_hash else None
    if info is not None:
        client_files = store_client_torrents(session, torrent_client, [info], scan_id)["files_linked"]
    logger.info(
        "Seed_job %s: %d hardlink registrati, %d file del torrent collegati nel client",
        seed_job.id, seed_files, client_files,
    )
    return {"seed_files": seed_files, "client_files": client_files}
