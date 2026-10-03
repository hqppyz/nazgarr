"""Le cartelle media e di seeding di un disco (decisione dell'utente,
2026-10-03): più di una per tipo, in disk_folder.

Una cartella si aggiunge solo se:
- è dentro il disco (resolve_scoped), esiste, e non è il disco intero;
- sta sullo stesso filesystem del disco: gli hardlink non attraversano i
  filesystem, e una cartella montata altrove va aggiunta come disco a sé;
- non coincide con un'altra cartella del disco, non ne contiene una e non
  sta dentro un'altra (una media dentro una di seeding conterebbe due volte
  gli stessi file);
- non contiene la cartella osservata (da dove le release se ne vanno).

Togliere una cartella non tocca niente sul disco: i suoi file escono dalla
libreria alla scansione successiva.
"""

import os

from sqlalchemy.orm import Session

from nazgarr.api_errors import CodedError
from nazgarr.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.models import DISK_FOLDER_KINDS, Disk, DiskFolder


class FolderError(CodedError):
    pass


def _inside_or_same(path: str, other: str) -> bool:
    return path == other or path.startswith(other + os.sep)


def validate(disk: Disk, kind: str, relative: str) -> str:
    """Il percorso relativo normalizzato, o FolderError con il motivo."""
    if kind not in DISK_FOLDER_KINDS:
        raise FolderError("folder_kind_invalid", kind=kind)
    try:
        path = resolve_scoped(disk.root_path, relative)
    except ScopeViolation as exc:
        raise FolderError("path_outside_scope", path=relative) from exc
    root = os.path.realpath(disk.root_path)
    if path == root:
        raise FolderError("folder_is_disk_root", path=relative)
    if not os.path.isdir(path):
        raise FolderError("folder_not_found", path=relative)
    if os.stat(path).st_dev != os.stat(root).st_dev:
        raise FolderError("folder_other_filesystem", path=relative)
    normalized = os.path.relpath(path, root)
    for folder in disk.folders:
        other = os.path.realpath(os.path.join(root, folder.relative_path))
        if folder.kind == kind and other == path:
            raise FolderError("folder_already_added", path=normalized)
        if _inside_or_same(path, other) or _inside_or_same(other, path):
            raise FolderError("folder_overlaps", path=normalized, other=folder.relative_path, kind=folder.kind)
    if disk.watch_rel_path:
        watch = os.path.realpath(os.path.join(root, disk.watch_rel_path))
        if _inside_or_same(path, watch):
            raise FolderError("folder_overlaps", path=normalized, other=disk.watch_rel_path, kind="watch")
    return normalized


def add(session: Session, disk: Disk, kind: str, relative: str) -> DiskFolder:
    _materialize_legacy(disk)
    normalized = validate(disk, kind, relative)
    folder = DiskFolder(disk=disk, kind=kind, relative_path=normalized)
    session.add(folder)
    session.commit()
    return folder


def remove(session: Session, disk: Disk, folder_id: int) -> bool:
    folder = next((f for f in disk.folders if f.id == folder_id), None)
    if folder is None:
        return False
    disk.folders.remove(folder)
    session.commit()
    return True


def replace(session: Session, disk: Disk, kind: str, relative: str | None) -> None:
    """Le API di prima (media_rel_path, torrents_rel_path): una sola cartella
    di quel tipo al posto di quelle che c'erano, o nessuna con "" / None."""
    _materialize_legacy(disk)
    kept = [f for f in disk.folders if f.kind != kind]
    previous = [f for f in disk.folders if f.kind == kind]
    disk.folders = kept
    session.flush()
    if relative:
        try:
            normalized = validate(disk, kind, relative)
        except FolderError:
            disk.folders = kept + previous
            raise
        disk.folders.append(DiskFolder(kind=kind, relative_path=normalized))
    session.commit()


def _materialize_legacy(disk: Disk) -> None:
    """Un disco non ancora migrato (creato in codice con i campi vecchi)
    porta in disk_folder le sue cartelle prima di cambiarle."""
    for kind, legacy in (("media", disk.media_rel_path), ("seeding", disk.torrents_rel_path)):
        if legacy and not any(f.kind == kind for f in disk.folders):
            disk.folders.append(DiskFolder(kind=kind, relative_path=legacy))
    disk.media_rel_path = disk.torrents_rel_path = None


def absolute(disk: Disk, kind: str) -> list[str]:
    """I percorsi assoluti (risolti) delle cartelle di quel tipo che stanno
    dentro il disco; una fuori scope si salta."""
    out = []
    for relative in disk.media_folders if kind == "media" else disk.seeding_folders:
        try:
            out.append(resolve_scoped(disk.root_path, relative))
        except ScopeViolation:
            continue
    return out
