"""Rilevamento duplicati: stesso contenuto, inode diversi — distinto dalla
verifica hardlink già esistente (st_dev+inode, usata per collegare
seed_file a media_file). Qui si cercano copie NON intenzionali dello
stesso contenuto in punti diversi della libreria media, che sprecano
spazio su disco senza che nessun hardlink le colleghi.

Fingerprint: MD5 dei primi e ultimi 64KB del file (l'intero file se più
piccolo di 128KB), non un hash crittografico del contenuto completo — un
compromesso deliberato: leggere per intero ogni video di una libreria
reale ad ogni scan sarebbe troppo costoso. Una collisione accidentale tra
due file di dimensione diversa e stesso fast-hash è già esclusa a monte
raggruppando anche per size_bytes. Stesso approccio (fast partial hash)
verificato nell'equivalente di Auditorr (get_fast_hash).
"""

import hashlib
import os

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from nazgarr.core.file_types import is_video
from nazgarr.core.models import MediaFile
from nazgarr.library.exclusions import load_exclusions
from nazgarr.library.scan_state import is_current, latest_scan_by_disk

_CHUNK_SIZE = 64 * 1024


def compute_fast_hash(path: str) -> str | None:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(_CHUNK_SIZE)
            tail = b""
            if size > _CHUNK_SIZE:
                f.seek(max(size - _CHUNK_SIZE, 0))
                tail = f.read(_CHUNK_SIZE)
        return hashlib.md5(head + tail).hexdigest()
    except OSError:
        return None


def find_duplicate_media_files(
    session: Session, disk_id: int | None = None, media_file_ids: list[int] | None = None,
) -> list[dict]:
    """Due tipi di gruppi (campo "kind"):
    - "copy": stesso (size_bytes, content_hash) su inode diversi, copie che
      sprecano spazio;
    - "hardlink": stesso inode con più percorsi in libreria, nessuno spazio
      in più ma lo stesso contenuto due volte.
    media_file_ids: solo i gruppi che possono contenere questi file (la
    scheda di un elemento), senza leggere tutta la libreria."""
    query = session.query(MediaFile).filter(MediaFile.content_hash.isnot(None))
    if disk_id is not None:
        query = query.filter_by(disk_id=disk_id)
    if media_file_ids is not None:
        # Un gruppo ha sempre stessa dimensione e stesso hash (anche gli
        # hardlink: stesso inode, stessi byte): bastano quelle coppie.
        keys = set(session.query(MediaFile.size_bytes, MediaFile.content_hash).filter(
            MediaFile.id.in_(media_file_ids), MediaFile.content_hash.isnot(None)).all())
        if not keys:
            return []
        query = query.filter(tuple_(MediaFile.size_bytes, MediaFile.content_hash).in_(list(keys)))

    groups: dict[tuple[int, str], list[MediaFile]] = {}
    latest = latest_scan_by_disk(session, MediaFile)
    exclusions = load_exclusions(session)
    for mf in query.all():
        if not is_current(mf, latest):
            continue  # sparito dal disco: non è più una copia di niente
        if exclusions.is_excluded(mf.relative_path):
            continue  # escluso = fuori da ogni controllo, anche da questo
        if not is_video(mf.relative_path):
            continue  # copie di nfo/immagini: rumore, nessuno spazio rilevante sprecato
        groups.setdefault((mf.size_bytes, mf.content_hash), []).append(mf)

    def entry(files: list[MediaFile]) -> list[dict]:
        return [
            {"media_file_id": mf.id, "disk_id": mf.disk_id, "relative_path": mf.relative_path}
            for mf in sorted(files, key=lambda f: f.relative_path)
        ]

    result = []
    for (size_bytes, content_hash), files in groups.items():
        distinct_inodes = {(mf.st_dev, mf.inode) for mf in files}
        if len(distinct_inodes) < 2:
            continue
        result.append({"content_hash": content_hash, "size_bytes": size_bytes, "kind": "copy", "files": entry(files)})

    # Stesso inode con due percorsi in libreria (es. un import doppio): nessuno
    # spazio sprecato, ma il contenuto compare due volte (media server,
    # Sonarr/Radarr) e uno dei due si può eliminare senza toccare il seed.
    by_inode: dict[tuple[int, int, int], list[MediaFile]] = {}
    for files in groups.values():
        for mf in files:
            by_inode.setdefault((mf.disk_id, mf.st_dev, mf.inode), []).append(mf)
    for files in by_inode.values():
        if len(files) > 1:
            result.append({
                "content_hash": files[0].content_hash, "size_bytes": files[0].size_bytes, "kind": "hardlink",
                "files": entry(files),
            })
    return sorted(result, key=lambda g: g["size_bytes"], reverse=True)
