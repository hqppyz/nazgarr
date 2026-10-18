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
import stat
from collections import defaultdict

from sqlalchemy import or_, tuple_
from sqlalchemy.orm import Session

from nazgarr.core.fs_scope import ScopeViolation, resolve_scoped
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
    target_exists (un altro file al suo posto, o un link simbolico: mai
    sovrascritto né seguito)."""

    def __init__(self, code: str, path: str, detail: str = ""):
        super().__init__(f"{code}: {path}")
        self.code, self.path, self.detail = code, path, detail


def _refuse_symlinks(root: str, target: str) -> None:
    """Nessun link simbolico fra root e la destinazione, sul percorso così
    come è scritto (audit 2026-10-18). resolve_scoped lo risolve, e prima il
    controllo guardava il percorso già risolto: un link simbolico al posto
    della destinazione veniva seguito, e l'hardlink nasceva dove puntava (il
    percorso approvato restava un link simbolico), o un link verso un
    hardlink già lì passava per un cross-seed da riusare. La destinazione è
    un target_exists; una cartella sopra è fuori scope, anche se punta
    dentro root: il torrent la vedrebbe da un'altra parte."""
    path = root
    parts = [part for part in os.path.relpath(target, root).split(os.sep) if part not in ("", ".")]
    if parts[:1] == [os.pardir]:
        raise ScopeViolation(target)  # fuori da root già come è scritto: niente da percorrere
    for i, part in enumerate(parts):
        path = os.path.join(path, part)
        if not os.path.islink(path):
            if not os.path.lexists(path):
                return  # da qui in giù non c'è niente: lo crea create_links
            continue
        if i == len(parts) - 1:
            raise LinkProblem("target_exists", target)
        raise ScopeViolation(path)


def check_link(source: str, target: str, root: str) -> str | None:
    """Prima di creare: la sorgente è un file vero (non un link simbolico),
    sullo stesso filesystem di root; nessun link simbolico sul percorso
    della destinazione (_refuse_symlinks: al suo posto è target_exists,
    dovunque punti, una cartella sopra è fuori scope), che resta dentro root
    anche a percorso risolto (ScopeViolation, nazgarr/core/fs_scope.py) ed è
    libera. Prima i link simbolici, poi la risoluzione: risolto, un link al
    posto della destinazione che punta fuori da root era un "fuori scope"
    invece di un target_exists (_refuse_symlinks guarda soltanto, con
    lstat, non scrive niente). Restituisce la destinazione risolta, da
    passare a create_links, o None se c'è già lo stesso file (un cross-seed
    con lo stesso nome: si riusa). Il percorso va passato così come è
    scritto, mai già risolto: risolto, un link simbolico al suo posto non
    si vede più."""
    if os.path.islink(source) or not os.path.isfile(source):
        raise LinkProblem("source_not_a_file", source)
    source_dev, root_dev = os.stat(source).st_dev, os.stat(root).st_dev
    if source_dev != root_dev:
        raise LinkProblem("cross_device", source, f"{source_dev} != {root_dev}")
    _refuse_symlinks(root, target)
    resolved = resolve_scoped(root, os.path.relpath(target, root))
    if os.path.lexists(resolved):
        if not os.path.samefile(source, resolved):
            raise LinkProblem("target_exists", target)
        return None
    return resolved


def make_dirs(path: str) -> None:
    """os.makedirs, ma ogni cartella nuova prende almeno i permessi e il
    gruppo della più vicina che c'era già: segue la disposizione del disco,
    non la umask del processo. Con la umask 077 di prima le cartelle create
    sui dischi nascevano 0700, e un client torrent con un altro utente dello
    stesso gruppo non ci entrava: recheck fallito, o un upload aggiunto senza
    recheck che poi non legge i pezzi (audit 2026-10-18)."""
    if os.path.isdir(path):
        return
    parent = os.path.dirname(path)
    if parent and parent != path:
        make_dirs(parent)
    try:
        os.mkdir(path)
    except FileExistsError:
        if os.path.isdir(path):
            return  # creata da qualcun altro nel frattempo: la sua resta com'è
        raise
    _like_parent(path, parent)


def _inherit(model: os.stat_result, current: os.stat_result, chmod, chown, label: str) -> None:
    """Aggiunge a una cartella appena creata i permessi di quella sopra, senza
    mai toglierne: rwx per Nazgarr restano sempre. Sulle condivisioni con le
    ACL (Synology, i dataset NFSv4 di TrueNAS) i bit di quella sopra possono
    valere 0 mentre si scrive grazie all'ACL: copiarli tali e quali lasciava
    la cartella a 0000, e l'hardlink dopo falliva con EACCES a ogni tentativo.
    Lì non si tocca niente: decide l'ACL ereditata."""
    try:
        model_bits = stat.S_IMODE(model.st_mode)
        if model_bits & 0o777:
            bits = stat.S_IMODE(current.st_mode)
            wanted = bits | (model_bits & 0o2777) | stat.S_IRWXU  # mai setuid o sticky
            if wanted != bits:
                chmod(wanted)
        if current.st_gid != model.st_gid:
            chown(model.st_gid)
    except OSError as exc:  # SMB decide i permessi al mount; un gruppo non nostro: EPERM
        logger.debug("Permessi di %s non copiati dalla cartella sopra: %s", label, exc)


def _like_parent(path: str, parent: str) -> None:
    try:
        model, current = os.stat(parent), os.stat(path)
    except OSError as exc:
        logger.debug("Permessi di %s non copiati da %s: %s", path, parent, exc)
        return
    _inherit(model, current, lambda bits: os.chmod(path, bits), lambda gid: os.chown(path, -1, gid), path)


# Gli hardlink si creano e si tolgono attraverso le cartelle aperte una per
# una, dalla radice del filesystem, senza mai seguire un link simbolico
# (O_NOFOLLOW): check_link guarda il percorso prima, ma fra il controllo e il
# link (una commit del DB, per l'esecutore) una cartella poteva diventare un
# link simbolico, e makedirs e link l'avrebbero seguito fuori dalla
# cartella approvata; lo stesso per un unlink dopo (audit 2026-10-18). Le
# destinazioni sono quelle che restituisce check_link, già risolte: un link
# simbolico che compare lungo il percorso vuol dire che qualcosa è cambiato,
# e l'operazione fallisce (ELOOP/ENOTDIR) invece di seguirlo.
# Le cartelle si aprono "solo per attraversarle" (O_PATH su Linux, O_SEARCH
# su macOS): come un percorso, basta il permesso di attraversamento (x), non
# quello di lettura, che una cartella 0711 di un NAS non dà. Solo quelle
# appena create si aprono in lettura, per copiarci i permessi (fchmod).
_NOFOLLOW_DIR = getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_DIR_FLAGS = (getattr(os, "O_PATH", 0) or getattr(os, "O_SEARCH", 0) or os.O_RDONLY) | _NOFOLLOW_DIR
_NEW_DIR_FLAGS = os.O_RDONLY | _NOFOLLOW_DIR
_FD_OPS = (hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW")
           and all(f in os.supports_dir_fd for f in (os.open, os.mkdir, os.link, os.unlink, os.rmdir)))


def _open_parent(path: str, create: bool) -> int:
    """Il descrittore della cartella che contiene path, aperta componente
    per componente senza seguire link simbolici; con create le cartelle che
    mancano si creano (con i permessi di quella sopra, come make_dirs)."""
    parts = [part for part in os.path.dirname(os.path.abspath(path)).split(os.sep) if part]
    fd = os.open(os.sep, _DIR_FLAGS)
    try:
        for part in parts:
            try:
                child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, dir_fd=fd)
                    made = True
                except FileExistsError:
                    made = False  # creata da qualcun altro nel frattempo: la sua resta com'è
                child = os.open(part, _NEW_DIR_FLAGS if made else _DIR_FLAGS, dir_fd=fd)
                if made:
                    _inherit(os.fstat(fd), os.fstat(child), lambda bits, c=child: os.fchmod(c, bits),
                             lambda gid, c=child: os.fchown(c, -1, gid), part)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _link(source: str, target: str) -> None:
    if not _FD_OPS:  # una piattaforma senza linkat/openat: per percorso, come prima
        make_dirs(os.path.dirname(target))
        os.link(source, target, follow_symlinks=False)
        return
    fd = _open_parent(target, create=True)
    try:
        os.link(source, os.path.basename(target), dst_dir_fd=fd, follow_symlinks=False)
    finally:
        os.close(fd)


def _unlink(path: str, directory: bool = False) -> None:
    remove = os.rmdir if directory else os.unlink
    if not _FD_OPS:
        remove(path)
        return
    fd = _open_parent(path, create=False)
    try:
        remove(os.path.basename(path), dir_fd=fd)
    finally:
        os.close(fd)


def create_links(pairs: list[tuple[str, str]]) -> list[str]:
    """Crea gli hardlink (sorgente, destinazione) già controllati con
    check_link (la destinazione che ha restituito), senza mai seguire link
    simbolici, nemmeno nelle cartelle sopra. Se uno fallisce, toglie quelli
    appena creati e rilancia: mai un torrent ricreato a metà. Restituisce le
    destinazioni create."""
    created: list[str] = []
    try:
        for source, target in pairs:
            _link(source, target)
            created.append(target)
    except OSError:
        remove_links(created)
        raise
    return created


def remove_links(paths: list[str], prune_up_to: str | None = None) -> None:
    """Toglie hardlink creati da questa esecuzione (mai i file di partenza),
    senza seguire link simbolici nelle cartelle sopra: una cartella diventata
    un link simbolico dopo la creazione non porta a togliere un file con lo
    stesso nome altrove. prune_up_to: toglie anche le cartelle rimaste vuote
    fra il file e quella cartella (esclusa)."""
    for path in paths:
        try:
            _unlink(path)
        except OSError:
            logger.warning("Impossibile rimuovere l'hardlink %s", path)
            continue
        if prune_up_to is None:
            continue
        stop = os.path.abspath(prune_up_to)
        parent = os.path.dirname(os.path.abspath(path))
        while parent.startswith(stop + os.sep):
            try:
                _unlink(parent, directory=True)  # solo se vuota
            except OSError:
                break
            parent = os.path.dirname(parent)
