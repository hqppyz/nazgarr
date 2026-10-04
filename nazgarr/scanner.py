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
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from nazgarr.db_utils import bulk_upsert
from nazgarr.duplicates import compute_fast_hash
from nazgarr.file_types import VIDEO_EXTENSIONS, is_video  # noqa: F401  (riesportati)
from nazgarr.models import Disk, MediaFile, RunLog, SeedFile
from nazgarr.scan_state import latest_scan_by_disk

logger = logging.getLogger(__name__)


def _list_files(abs_root: str) -> list[str]:
    """Ogni file sotto abs_root, solo i nomi (nessuno stat): un primo giro
    veloce che dà il totale per l'avanzamento prima della parte lenta."""
    if not os.path.isdir(abs_root):
        logger.warning("Percorso non raggiungibile, salto: %s", abs_root)
        return []
    # I symlink no: un link in libreria verso un file qualsiasi dello stesso
    # disco (il DB, una chiave) finirebbe hardlinkato nella cartella torrent
    # e messo in seed. Né file né cartelle-link: scandir lo sa già dalla
    # lettura della cartella, senza un lstat per file (su una share di rete
    # è una richiesta in meno per ogni file).
    out: list[str] = []
    pending = [abs_root]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
                    else:
                        out.append(entry.path)
        except OSError as exc:
            logger.warning("Cartella non leggibile, salto: %s", exc)
    return out


# stat + hash parziale in parallelo: operazioni di I/O indipendenti, che su
# un disco di rete o FUSE (file su dischi fisici diversi) si sovrappongono
# bene. Nessun accesso al DB nei thread.
STAT_WORKERS = 8


def _stat_one(full_path: str, with_hash: bool, known: dict | None = None):
    try:
        st = os.stat(full_path)
    except OSError as exc:
        logger.warning("Impossibile leggere %r: %s", full_path, exc)
        return full_path, None, None
    # Hash parziale (128KB, nazgarr/duplicates.py) solo per i video: i duplicati
    # riguardano solo loro, leggere ogni nfo o immagine sarebbe spreco.
    if not with_hash or not is_video(full_path):
        return full_path, st, None
    # Stesso file della scansione precedente (stesso inode, dimensione e
    # mtime): l'hash di allora vale ancora, niente da rileggere.
    previous = (known or {}).get(full_path)
    if previous is not None and previous[:4] == (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) and previous[4]:
        return full_path, st, previous[4]
    return full_path, st, compute_fast_hash(full_path)


def _stat_files(
    paths: list[str], on_progress: Callable[[int], None] | None, with_hash: bool = False, known: dict | None = None,
):
    """(path, stat, content_hash) per ogni file ancora leggibile, nello stesso
    ordine di `paths`. Un errore di stat su un singolo file (permessi, file
    sparito dopo l'elenco) viene loggato e saltato — non deve mai far
    fallire l'intero scan. on_progress è chiamato nel thread chiamante.
    known: percorso -> (st_dev, inode, size, mtime_ns, content_hash) della
    scansione precedente, per riusare gli hash dei file invariati."""
    pool = ThreadPoolExecutor(max_workers=STAT_WORKERS)
    try:
        for full_path, st, content_hash in pool.map(lambda p: _stat_one(p, with_hash, known), paths):
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
    # Le cartelle (relative al disco) che non si sono potute leggere, per
    # tipo: i loro file restano com'erano, mai "spariti" (vedi scan_disk).
    unreachable: dict[str, list[str]] = field(default_factory=lambda: {"media": [], "seeding": []})
    # Quante cartelle per tipo sono state lette davvero.
    read: dict[str, int] = field(default_factory=lambda: {"media": 0, "seeding": 0})

    def __len__(self) -> int:
        return len(self.media) + len(self.seeds)


def list_disk_files(disk: Disk) -> DiskFiles:
    """I file di tutte le cartelle media e di seeding del disco
    (disk_folder: più di una per tipo, nazgarr/disk_folders.py)."""
    files = DiskFiles(media=[], seeds=[])
    for kind, folders, out in (("media", disk.media_folders, files.media),
                               ("seeding", disk.seeding_folders, files.seeds)):
        for relative in folders:
            abs_root = os.path.join(disk.root_path, relative)
            if not os.path.isdir(abs_root):
                logger.warning("Cartella %s non raggiungibile, i suoi file restano com'erano: %s", kind, abs_root)
                files.unreachable[kind].append(relative)
                continue
            files.read[kind] += 1
            out.extend(_list_files(abs_root))
    return files


def _keep_current(session: Session, model, disk: Disk, folders: list[str], previous: int | None, run_id: int) -> None:
    """Le righe ancora attuali di una cartella che questo scan non ha potuto
    leggere (una share non montata) restano attuali: senza, sparirebbero
    dalla libreria insieme alla cartella. Solo quelle attuali fino a ora,
    mai un file già sparito prima."""
    if previous is None:
        return
    for relative in folders:
        prefix = relative.rstrip("/") + "/"
        (
            session.query(model)
            .filter(model.disk_id == disk.id, model.last_scan_id == previous,
                    func.substr(model.relative_path, 1, len(prefix)) == prefix)
            .update({"last_scan_id": run_id}, synchronize_session=False)
        )


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
    previous_media = latest_scan_by_disk(session, MediaFile).get(disk.id)
    previous_seed = latest_scan_by_disk(session, SeedFile).get(disk.id)
    media_rows: list[dict] = []
    if files.media:
        known = {
            os.path.join(disk.root_path, rel): (dev, ino, size, mtime, content_hash)
            for rel, dev, ino, size, mtime, content_hash in session.query(
                MediaFile.relative_path, MediaFile.st_dev, MediaFile.inode, MediaFile.size_bytes, MediaFile.mtime_ns,
                MediaFile.content_hash,
            ).filter(MediaFile.disk_id == disk.id, MediaFile.mtime_ns.isnot(None)).all()
        }
        for full_path, st, content_hash in _stat_files(files.media, on_progress, with_hash=True, known=known):
            media_rows.append({
                "disk_id": disk.id,
                "relative_path": os.path.relpath(full_path, disk.root_path),
                "size_bytes": st.st_size,
                "st_dev": st.st_dev,
                "inode": st.st_ino,
                "nlink": st.st_nlink,
                # Costo limitato a 128KB/file indipendentemente dalla dimensione
                # (nazgarr/duplicates.py), solo per i video, e riletto solo se il
                # file è cambiato dalla scansione precedente (mtime_ns).
                "content_hash": content_hash,
                "mtime_ns": st.st_mtime_ns,
                "last_scan_id": run.id,
                "last_seen_at": now,
            })

    bulk_upsert(
        session, MediaFile.__table__, media_rows,
        conflict_cols=["disk_id", "relative_path"],
        update_cols=[
            "size_bytes", "st_dev", "inode", "nlink", "content_hash", "mtime_ns",
            "last_scan_id", "last_seen_at",
        ],
    )
    _keep_current(session, MediaFile, disk, files.unreachable["media"], previous_media, run.id)
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
    _keep_current(session, SeedFile, disk, files.unreachable["seeding"], previous_seed, run.id)
    # Il lato letto davvero (almeno una cartella presente), anche se vuoto: da
    # qui in poi i suoi file non rivisti sono spariti (nazgarr/scan_state.py).
    # Una cartella irraggiungibile tiene attuali i suoi (_keep_current); se
    # nessuna si è potuta leggere, niente cambia, nel dubbio restano attuali.
    if files.read["media"]:
        disk.media_scan_id = run.id
    if files.read["seeding"]:
        disk.seed_scan_id = run.id
    session.commit()

    return {"media_files_scanned": len(media_rows), "seed_files_scanned": len(seed_rows)}
