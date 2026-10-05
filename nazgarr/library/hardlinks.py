"""Quali file della libreria sono hardlinkati a quali file della cartella
torrent, per inode.

seed_file.media_file_id (scritto dallo scanner) collega ogni file lato
torrent a UN solo media_file con lo stesso inode: basta per l'identità del
file torrent, ma se in libreria lo stesso inode ha due percorsi (es. un
import doppio di Sonarr/Radarr) il secondo restava senza collegamento,
"orphaned" pur essendo fisicamente lo stesso file già in seed, e il
matching lo cercava sui tracker. Qui il collegamento è per
(disk_id, st_dev, inode): ogni percorso in libreria di quell'inode vede
tutti i suoi hardlink lato torrent.

Solo i file visti dall'ultima scansione del loro disco: lo scanner non
cancella le righe dei file spariti (restano con un last_scan_id vecchio), e
un file lato torrent cancellato risultava ancora hardlink del file in
libreria, per il collegamento esplicito rimasto o perché il filesystem ne
aveva riusato l'inode per un file nuovo.

Qui anche la creazione: check_link e create_links sono l'unico modo in cui
l'esecuzione delle review (nazgarr/reseed/executor.py) e l'upload
(nazgarr/upload/execute.py) creano hardlink.
"""

import logging
import os
from collections import defaultdict

from sqlalchemy import or_, tuple_
from sqlalchemy.orm import Session

from nazgarr.core.fs_scope import resolve_scoped
from nazgarr.core.models import MediaFile, SeedFile
from nazgarr.library.scan_state import latest_scan_by_disk


def media_links(session: Session, media_file_ids: list[int] | None = None) -> dict[int, list[tuple[int, str]]]:
    """media_file.id -> [(seed_file.id, seed_file.relative_path)]: i file lato
    torrent con lo stesso inode sullo stesso disco, più quelli già collegati
    esplicitamente (seed_file.media_file_id, scanner e nazgarr/library/seed_refresh.py).
    Solo i media_file con almeno un link."""
    wanted = set(media_file_ids) if media_file_ids is not None else None
    seeds: dict[tuple[int, int, int], list[tuple[int, str]]] = defaultdict(list)
    links: dict[int, dict[int, str]] = defaultdict(dict)
    latest_seed = latest_scan_by_disk(session, SeedFile)
    latest_media = latest_scan_by_disk(session, MediaFile)
    seed_query = session.query(
        SeedFile.id, SeedFile.disk_id, SeedFile.st_dev, SeedFile.inode, SeedFile.relative_path, SeedFile.media_file_id,
        SeedFile.last_scan_id,
    )
    if wanted is not None:
        # Pochi file (la scheda di un elemento): solo i seed_file con i loro
        # inode o già collegati a loro, non tutto il lato torrent.
        inodes = session.query(MediaFile.disk_id, MediaFile.st_dev, MediaFile.inode).filter(
            MediaFile.id.in_(wanted)).all()
        seed_query = seed_query.filter(or_(
            tuple_(SeedFile.disk_id, SeedFile.st_dev, SeedFile.inode).in_([tuple(r) for r in inodes]),
            SeedFile.media_file_id.in_(wanted),
        ))
    for sf_id, disk_id, st_dev, inode, path, media_file_id, last_scan_id in seed_query.all():
        if last_scan_id != latest_seed.get(disk_id, last_scan_id):
            continue  # sparito dal disco: non è più un hardlink di niente
        seeds[(disk_id, st_dev, inode)].append((sf_id, path))
        if media_file_id is not None and (wanted is None or media_file_id in wanted):
            links[media_file_id][sf_id] = path
    if not seeds:
        return {}
    query = session.query(MediaFile.id, MediaFile.disk_id, MediaFile.st_dev, MediaFile.inode, MediaFile.last_scan_id)
    if wanted is not None:
        query = query.filter(MediaFile.id.in_(wanted))
    for mf_id, disk_id, st_dev, inode, last_scan_id in query.all():
        if last_scan_id != latest_media.get(disk_id, last_scan_id):
            links.pop(mf_id, None)
            continue
        for sf_id, path in seeds.get((disk_id, st_dev, inode), ()):
            links[mf_id][sf_id] = path
    return {mf_id: sorted(sfs.items(), key=lambda item: item[1]) for mf_id, sfs in links.items()}


def seed_copies_by_inode(session: Session) -> dict[tuple[int, int, int], set[int]]:
    """(disk_id, st_dev, inode) -> seed_file attuali con quell'inode, solo
    dove sono più di uno: le copie (hardlink) dello stesso file lato torrent."""
    latest = latest_scan_by_disk(session, SeedFile)
    groups: dict[tuple[int, int, int], set[int]] = {}
    for sf_id, disk_id, st_dev, inode, last_scan_id in session.query(
        SeedFile.id, SeedFile.disk_id, SeedFile.st_dev, SeedFile.inode, SeedFile.last_scan_id,
    ).all():
        if last_scan_id == latest.get(disk_id, last_scan_id):
            groups.setdefault((disk_id, st_dev, inode), set()).add(sf_id)
    return {key: ids for key, ids in groups.items() if len(ids) > 1}


logger = logging.getLogger(__name__)


class LinkProblem(Exception):
    """Un hardlink che non si può creare. code: source_not_a_file (un symlink
    o niente), cross_device (un hardlink non attraversa i filesystem),
    target_exists (un altro file al suo posto: mai sovrascritto)."""

    def __init__(self, code: str, path: str, detail: str = ""):
        super().__init__(f"{code}: {path}")
        self.code, self.path, self.detail = code, path, detail


def check_link(source: str, target: str, root: str) -> str | None:
    """Prima di creare: la sorgente è un file vero (non un link simbolico),
    sullo stesso filesystem di root; la destinazione resta dentro root anche
    a percorso risolto (ScopeViolation, nazgarr/core/fs_scope.py) ed è libera.
    Restituisce la destinazione risolta, o None se c'è già lo stesso file
    (un cross-seed con lo stesso nome: si riusa)."""
    if os.path.islink(source) or not os.path.isfile(source):
        raise LinkProblem("source_not_a_file", source)
    source_dev, root_dev = os.stat(source).st_dev, os.stat(root).st_dev
    if source_dev != root_dev:
        raise LinkProblem("cross_device", source, f"{source_dev} != {root_dev}")
    resolved = resolve_scoped(root, os.path.relpath(target, root))
    if os.path.lexists(resolved):
        if os.path.islink(resolved) or not os.path.samefile(source, resolved):
            raise LinkProblem("target_exists", target)
        return None
    return resolved


def create_links(pairs: list[tuple[str, str]]) -> list[str]:
    """Crea gli hardlink (sorgente, destinazione) già controllati con
    check_link, senza mai seguire link simbolici. Se uno fallisce, toglie
    quelli appena creati e rilancia: mai un torrent ricreato a metà.
    Restituisce le destinazioni create."""
    created: list[str] = []
    try:
        for source, target in pairs:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.link(source, target, follow_symlinks=False)
            created.append(target)
    except OSError:
        remove_links(created)
        raise
    return created


def remove_links(paths: list[str]) -> None:
    """Toglie hardlink creati da questa esecuzione (mai i file di partenza)."""
    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            logger.warning("Impossibile rimuovere l'hardlink %s", path)
