"""Scansione filesystem: popola media_file e seed_file, rileva gli hardlink.

Vedi docs/SPEC.md sezione 4 per il razionale completo. Punti chiave da
rispettare qui, non altrove:

- Il grouping per hardlink (st_dev, inode) va calcolato IN MEMORIA durante
  il walk, mai con un self-join SQL a runtime.
- seed_file.media_file_id va scritto SOLO da questo modulo, con un bulk
  upsert a fine scan — mai una query/update per singolo file.
- Le righe non riviste in questo scan (file spostato/cancellato) non
  vanno cancellate: restano con un last_scan_id vecchio, così una query
  sullo stato corrente (filtrata su last_scan_id = run corrente) le
  esclude naturalmente senza bisogno di un DELETE esplicito.

L'orchestrazione di una run intera (questo scan + l'indicizzazione dei
client torrent di nazgarr/torrent_indexer.py, sempre in questo ordine) vive in
nazgarr/pipeline.py, non qui — questo modulo resta scoped al solo filesystem.
"""

import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from nazgarr.db_utils import bulk_upsert
from nazgarr.duplicates import compute_fast_hash
from nazgarr.file_types import VIDEO_EXTENSIONS, is_video  # noqa: F401  (riesportati)
from nazgarr.models import Disk, MediaFile, RunLog, SeedFile

logger = logging.getLogger(__name__)


def _list_files(abs_root: str) -> list[str]:
    """Ogni file sotto abs_root, solo i nomi (nessuno stat): un primo giro
    veloce che dà il totale per l'avanzamento prima della parte lenta."""
    if not os.path.isdir(abs_root):
        logger.warning("Percorso non raggiungibile, salto: %s", abs_root)
        return []
    # I symlink no: un link in libreria verso un file qualsiasi dello stesso
    # disco (il DB, una chiave) finirebbe hardlinkato nella cartella torrent
    # e messo in seed. os.walk già non entra nelle cartelle-link.
    return [
        path for dirpath, _dirs, names in os.walk(abs_root) for name in names
        if not os.path.islink(path := os.path.join(dirpath, name))
    ]


# stat + hash parziale in parallelo: operazioni di I/O indipendenti, che su
# un disco di rete o FUSE (file su dischi fisici diversi) si sovrappongono
# bene. Nessun accesso al DB nei thread.
STAT_WORKERS = 8


def _stat_one(full_path: str, with_hash: bool):
    try:
        st = os.stat(full_path)
    except OSError as exc:
        logger.warning("Impossibile leggere %r: %s", full_path, exc)
        return full_path, None, None
    # Hash parziale (128KB, nazgarr/duplicates.py) solo per i video: i duplicati
    # riguardano solo loro, leggere ogni nfo o immagine sarebbe spreco.
    content_hash = compute_fast_hash(full_path) if with_hash and is_video(full_path) else None
    return full_path, st, content_hash


def _stat_files(paths: list[str], on_progress: Callable[[int], None] | None, with_hash: bool = False):
    """(path, stat, content_hash) per ogni file ancora leggibile, nello stesso
    ordine di `paths`. Un errore di stat su un singolo file (permessi, file
    sparito dopo l'elenco) viene loggato e saltato — non deve mai far
    fallire l'intero scan. on_progress è chiamato nel thread chiamante."""
    pool = ThreadPoolExecutor(max_workers=STAT_WORKERS)
    try:
        for full_path, st, content_hash in pool.map(lambda p: _stat_one(p, with_hash), paths):
            if st is not None:
                yield full_path, st, content_hash
            if on_progress is not None:
                on_progress(1)
    finally:
        # Su uno stop (RunCancelled da on_progress) o un errore, i file non
        # ancora iniziati si annullano: niente attesa fino a fine disco.
        pool.shutdown(wait=True, cancel_futures=True)


@dataclass
class DiskFiles:
    media: list[str]
    seeds: list[str]

    def __len__(self) -> int:
        return len(self.media) + len(self.seeds)


def list_disk_files(disk: Disk) -> DiskFiles:
    media = _list_files(os.path.join(disk.root_path, disk.media_rel_path)) if disk.media_rel_path else []
    seeds = _list_files(os.path.join(disk.root_path, disk.torrents_rel_path)) if disk.torrents_rel_path else []
    return DiskFiles(media=media, seeds=seeds)


def scan_disk(
    session: Session,
    disk: Disk,
    run: RunLog,
    files: DiskFiles | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> dict[str, int]:
    """Scansiona un disco: la sua cartella media e la sua cartella torrent,
    se configurate — ogni file su entrambi i lati, video e non. I file
    extra (nfo, sottotitoli, sample) servono per ricreare torrent che li
    contengono; nasconderli da viste e conteggi è compito delle esclusioni
    (nazgarr/exclusions.py), mai dello scanner."""
    now = datetime.now(UTC)
    files = files if files is not None else list_disk_files(disk)
    media_rows: list[dict] = []
    if files.media:
        for full_path, st, content_hash in _stat_files(files.media, on_progress, with_hash=True):
            media_rows.append({
                "disk_id": disk.id,
                "relative_path": os.path.relpath(full_path, disk.root_path),
                "size_bytes": st.st_size,
                "st_dev": st.st_dev,
                "inode": st.st_ino,
                "nlink": st.st_nlink,
                # Costo limitato a 128KB/file indipendentemente dalla dimensione
                # (nazgarr/duplicates.py), solo per i video — ricalcolato a ogni
                # scan, nessuna cache incrementale ancora.
                "content_hash": content_hash,
                "last_scan_id": run.id,
                "last_seen_at": now,
            })

    bulk_upsert(
        session, MediaFile.__table__, media_rows,
        conflict_cols=["disk_id", "relative_path"],
        update_cols=[
            "size_bytes", "st_dev", "inode", "nlink", "content_hash",
            "last_scan_id", "last_seen_at",
        ],
    )
    session.commit()

    # (st_dev, inode) -> media_file.id per QUESTO disco, per risolvere seed_file.media_file_id
    # sotto senza una query per riga. Se più media_file condividono lo stesso inode (raro:
    # hardlink duplicato dentro la libreria stessa), vince quello con id più basso — gli altri
    # restano comunque visibili interrogando media_file per (disk_id, st_dev, inode).
    # Solo i file visti in QUESTO scan: una riga di un file cancellato resta
    # (con un last_scan_id vecchio), e se il filesystem ne ha riusato l'inode
    # per un file nuovo lato torrent, quel file finiva collegato a un file in
    # libreria che non c'è più.
    inode_to_media_file_id: dict[tuple[int, int], int] = {}
    for media_file_id, st_dev, inode in (
        session.query(MediaFile.id, MediaFile.st_dev, MediaFile.inode)
        .filter_by(disk_id=disk.id, last_scan_id=run.id)
        .order_by(MediaFile.id)
        .all()
    ):
        inode_to_media_file_id.setdefault((st_dev, inode), media_file_id)

    seed_rows: list[dict] = []
    if files.seeds:
        for full_path, st, _hash in _stat_files(files.seeds, on_progress):
            seed_rows.append({
                "disk_id": disk.id,
                "relative_path": os.path.relpath(full_path, disk.root_path),
                "size_bytes": st.st_size,
                "st_dev": st.st_dev,
                "inode": st.st_ino,
                "media_file_id": inode_to_media_file_id.get((st.st_dev, st.st_ino)),
                "last_scan_id": run.id,
                "last_seen_at": now,
            })

    bulk_upsert(
        session, SeedFile.__table__, seed_rows,
        conflict_cols=["disk_id", "relative_path"],
        update_cols=["size_bytes", "st_dev", "inode", "media_file_id", "last_scan_id", "last_seen_at"],
    )
    # Il lato letto davvero (cartella presente), anche se vuoto: da qui in poi i
    # suoi file non rivisti sono spariti (nazgarr/scan_state.py). Una cartella
    # irraggiungibile non aggiorna niente, nel dubbio i file restano attuali.
    if disk.media_rel_path and os.path.isdir(os.path.join(disk.root_path, disk.media_rel_path)):
        disk.media_scan_id = run.id
    if disk.torrents_rel_path and os.path.isdir(os.path.join(disk.root_path, disk.torrents_rel_path)):
        disk.seed_scan_id = run.id
    session.commit()

    return {"media_files_scanned": len(media_rows), "seed_files_scanned": len(seed_rows)}
