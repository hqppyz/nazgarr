"""File Browser API scoped-per-disco.

Vedi docs/SPEC.md sezione 4 (ereditata da ratio-guardian). Usata sia per
scegliere le cartelle media e di seeding di un disco (disk_folder,
nazgarr/disk_folders.py) che le altre sue cartelle — un solo meccanismo di
scoping condiviso (nazgarr/fs_scope.py), mai duplicato.

Nazgarr è un'API JSON pura fin dall'inizio (a differenza di
ratio-guardian, che ha ancora una Web UI Jinja2): anche l'elenco dei mount
disponibili sotto disk_scan_root (usato lì solo dalla pagina web) è quindi
esposto qui come endpoint proprio.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nazgarr import disk_folders
from nazgarr.api_errors import CodedError, coded_detail, from_coded_error
from nazgarr.deps import get_session
from nazgarr.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.models import ClientTorrentFile, Disk, SeedFile

router = APIRouter(prefix="/api/disks", tags=["disks"])


class BrowseEntry(BaseModel):
    name: str
    is_dir: bool
    size_bytes: int | None = None  # solo per i file


class BrowseResponse(BaseModel):
    disk_id: int
    current_path: str
    entries: list[BrowseEntry]


class MkdirRequest(BaseModel):
    path: str


class MkdirResponse(BaseModel):
    path: str
    created: bool


class VerifyResponse(BaseModel):
    consistent: bool
    warning: str | None = None


class DiskCreateRequest(BaseModel):
    label: str
    root_path: str


class DiskUpdateRequest(BaseModel):
    label: str | None = None
    # Deprecati: una sola cartella al posto di tutte quelle di quel tipo ("" le
    # toglie). Le cartelle si gestiscono con /api/disks/{id}/folders.
    media_rel_path: str | None = None
    torrents_rel_path: str | None = None
    new_torrent_rel_path: str | None = None
    upload_rel_path: str | None = None
    watch_rel_path: str | None = None  # "" la toglie


class DiskFolderResponse(BaseModel):
    id: int | None  # None: un disco non ancora migrato (nazgarr/db.py migrate_disk_folders)
    kind: str  # media | seeding
    relative_path: str


class DiskFolderRequest(BaseModel):
    kind: str
    relative_path: str


class DiskResponse(BaseModel):
    id: int
    label: str
    root_path: str
    folders: list[DiskFolderResponse] = []
    media_folders: list[str] = []
    seeding_folders: list[str] = []
    # Deprecati: la prima cartella di quel tipo (media_folders, seeding_folders).
    media_rel_path: str | None
    torrents_rel_path: str | None
    new_torrent_rel_path: str | None
    upload_rel_path: str | None
    watch_rel_path: str | None = None
    st_dev: int | None

    @classmethod
    def from_model(cls, disk: Disk) -> "DiskResponse":
        return cls(
            id=disk.id, label=disk.label, root_path=disk.root_path,
            folders=[DiskFolderResponse(id=f.id, kind=f.kind, relative_path=f.relative_path) for f in disk.folders]
            or [DiskFolderResponse(id=None, kind=kind, relative_path=path)
                for kind, path in (("media", disk.media_rel_path), ("seeding", disk.torrents_rel_path)) if path],
            media_folders=disk.media_folders, seeding_folders=disk.seeding_folders,
            media_rel_path=next(iter(disk.media_folders), None),
            torrents_rel_path=next(iter(disk.seeding_folders), None),
            new_torrent_rel_path=disk.new_torrent_rel_path, upload_rel_path=disk.upload_rel_path,
            watch_rel_path=disk.watch_rel_path,
            st_dev=disk.st_dev,
        )


class AvailableMountsResponse(BaseModel):
    scan_root: str
    mounts: list[str]


class DiskValidationError(CodedError):
    pass


class DiskConflictError(CodedError):
    pass


def _get_disk_or_404(session: Session, disk_id: int) -> Disk:
    disk = session.get(Disk, disk_id)
    if disk is None:
        raise HTTPException(status_code=404, detail=coded_detail("disk_not_found", id=disk_id))
    return disk


def is_within_scan_root(path: str, scan_root: str) -> bool:
    real = os.path.realpath(path)
    real_root = os.path.realpath(scan_root)
    return real == real_root or real.startswith(real_root + os.sep)


def list_available_mounts(scan_root: str, used_paths: set[str]) -> list[str]:
    """Sottocartelle di primo livello di scan_root non ancora assegnate a
    un Disk — sono i bind mount dei dischi fisici (vedi docker-compose.yml,
    che li monta 1:1 sotto scan_root, di default /mnt) non ancora aggiunti
    dalla Web UI. Nessuna dipendenza da config.yaml: basta il bind mount
    Docker perché un disco compaia qui."""
    if not os.path.isdir(scan_root):
        return []
    used_real = {os.path.realpath(p) for p in used_paths}
    mounts = [
        entry.path
        for entry in os.scandir(scan_root)
        if entry.is_dir() and os.path.realpath(entry.path) not in used_real
    ]
    return sorted(mounts)


def create_disk(session: Session, label: str, root_path: str, scan_root: str) -> Disk:
    if not os.path.isdir(root_path):
        raise DiskValidationError("disk_root_path_not_a_directory", path=root_path)
    if not is_within_scan_root(root_path, scan_root):
        raise DiskValidationError("disk_root_path_outside_scan_root", scan_root=scan_root)
    disk = Disk(label=label, root_path=root_path)
    session.add(disk)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DiskConflictError("disk_root_path_conflict", path=root_path) from exc
    return disk


def verify_disk(session: Session, disk: Disk) -> VerifyResponse:
    if not os.path.isdir(disk.root_path):
        raise HTTPException(status_code=404, detail=coded_detail("disk_root_path_unreachable", path=disk.root_path))

    current_st_dev = os.stat(disk.root_path).st_dev

    if disk.st_dev is None:
        # Prima verifica: non c'è nulla con cui confrontare, stabiliamo la baseline.
        disk.st_dev = current_st_dev
        session.commit()
        return VerifyResponse(consistent=True)

    if current_st_dev != disk.st_dev:
        # Non sovrascriviamo mai silenziosamente: st_dev cambiato = possibile
        # rimonto/sostituzione del disco (vedi docs/SPEC.md sezione 4).
        return VerifyResponse(
            consistent=False,
            warning=(
                f"st_dev changed for disk '{disk.label}' "
                f"({disk.st_dev} -> {current_st_dev}): the disk may have been remounted "
                "or replaced. Verify before proceeding with hardlinks."
            ),
        )

    return VerifyResponse(consistent=True)


def _relative_to_root(root_path: str, candidate: str) -> str:
    rel = os.path.relpath(candidate, os.path.realpath(root_path))
    return "" if rel == "." else rel


def _resolve_or_400(disk: Disk, relative: str) -> str:
    try:
        return resolve_scoped(disk.root_path, relative)
    except ScopeViolation as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc


@router.get("/available-mounts", response_model=AvailableMountsResponse)
def available_mounts(request: Request, session: Session = Depends(get_session)):
    scan_root = request.app.state.settings.disk_scan_root
    used_paths = {d.root_path for d in session.query(Disk).all()}
    return AvailableMountsResponse(scan_root=scan_root, mounts=list_available_mounts(scan_root, used_paths))


def _browse_entry(entry: os.DirEntry) -> BrowseEntry:
    is_dir = entry.is_dir()
    size = None
    if not is_dir:
        try:
            size = entry.stat().st_size
        except OSError:
            pass  # link rotto o file sparito nel frattempo: nessuna dimensione
    return BrowseEntry(name=entry.name, is_dir=is_dir, size_bytes=size)


@router.get("/{disk_id}/browse", response_model=BrowseResponse)
def browse(disk_id: int, path: str = "", session: Session = Depends(get_session)):
    disk = _get_disk_or_404(session, disk_id)
    candidate = _resolve_or_400(disk, path)

    if not os.path.isdir(candidate):
        raise HTTPException(status_code=404, detail=coded_detail("path_not_found", path=path))

    entries = sorted((_browse_entry(e) for e in os.scandir(candidate)), key=lambda e: e.name.lower())
    return BrowseResponse(
        disk_id=disk.id,
        current_path=_relative_to_root(disk.root_path, candidate),
        entries=entries,
    )


@router.post("/{disk_id}/mkdir", response_model=MkdirResponse, status_code=201)
def mkdir(disk_id: int, body: MkdirRequest, session: Session = Depends(get_session)):
    disk = _get_disk_or_404(session, disk_id)
    candidate = _resolve_or_400(disk, body.path)

    if os.path.exists(candidate):
        raise HTTPException(status_code=409, detail=coded_detail("folder_already_exists", path=body.path))

    os.makedirs(candidate)
    return MkdirResponse(path=_relative_to_root(disk.root_path, candidate), created=True)


@router.post("/{disk_id}/verify", response_model=VerifyResponse)
def verify(disk_id: int, session: Session = Depends(get_session)):
    disk = _get_disk_or_404(session, disk_id)
    return verify_disk(session, disk)


@router.get("", response_model=list[DiskResponse])
def list_disks(session: Session = Depends(get_session)):
    return [DiskResponse.from_model(d) for d in session.query(Disk).all()]


@router.post("", response_model=DiskResponse, status_code=201)
def create_disk_endpoint(body: DiskCreateRequest, request: Request, session: Session = Depends(get_session)):
    try:
        disk = create_disk(session, body.label, body.root_path, request.app.state.settings.disk_scan_root)
    except DiskValidationError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    except DiskConflictError as exc:
        raise HTTPException(status_code=409, detail=from_coded_error(exc)) from exc
    return DiskResponse.from_model(disk)


@router.patch("/{disk_id}", response_model=DiskResponse)
def update_disk(disk_id: int, body: DiskUpdateRequest, session: Session = Depends(get_session)):
    disk = _get_disk_or_404(session, disk_id)
    if body.label is not None:
        disk.label = body.label
    try:
        if body.media_rel_path is not None:
            disk_folders.replace(session, disk, "media", body.media_rel_path or None)
        if body.torrents_rel_path is not None:
            disk_folders.replace(session, disk, "seeding", body.torrents_rel_path or None)
    except disk_folders.FolderError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    if body.new_torrent_rel_path is not None:
        disk.new_torrent_rel_path = body.new_torrent_rel_path or None
    if body.upload_rel_path is not None:
        disk.upload_rel_path = body.upload_rel_path or None
    if body.watch_rel_path is not None and (body.watch_rel_path or None) != disk.watch_rel_path:
        disk.watch_rel_path = _watch_folder(session, disk, body.watch_rel_path or None)
    session.commit()
    return DiskResponse.from_model(disk)


def _watch_folder(session: Session, disk: Disk, relative: str | None) -> str | None:
    """La cartella osservata: dentro il disco ed esistente. Mai il disco
    intero, la cartella media, quella dei torrent o quella degli upload (né
    una che le contiene), e mai una dove un client scarica o seeda: ogni
    download partirebbe come una release. Una sottocartella dedicata (es.
    torrents/watch) va bene."""
    if relative is None:
        return None
    try:
        path = resolve_scoped(disk.root_path, relative)
    except ScopeViolation as exc:
        raise HTTPException(status_code=400, detail=coded_detail("path_outside_scope", path=relative)) from exc
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=coded_detail("watch_folder_not_found", path=relative))
    root = os.path.realpath(disk.root_path)
    if path == root:
        raise HTTPException(status_code=400, detail=coded_detail("watch_folder_overlaps", path=relative))
    for other in (*disk.media_folders, *disk.seeding_folders, disk.effective_upload_rel_path):
        if not other:
            continue
        other_path = os.path.realpath(os.path.join(disk.root_path, other))
        if path == other_path or other_path.startswith(path + os.sep):
            raise HTTPException(status_code=400, detail=coded_detail("watch_folder_overlaps", path=relative))
    relative_path = os.path.relpath(path, root)
    # Dove un client scarica o seeda: un file di un suo torrent è lì dentro.
    tracked = (
        session.query(SeedFile.relative_path)
        .join(ClientTorrentFile, ClientTorrentFile.seed_file_id == SeedFile.id)
        .filter(SeedFile.disk_id == disk.id)
    )
    if any(seed_path.startswith(relative_path + "/") for (seed_path,) in tracked):
        raise HTTPException(status_code=400, detail=coded_detail("watch_folder_used_by_client", path=relative))
    return relative_path


@router.post("/{disk_id}/folders", response_model=DiskResponse, status_code=201)
def add_folder(disk_id: int, body: DiskFolderRequest, session: Session = Depends(get_session)):
    """Una cartella media o di seeding in più (nazgarr/disk_folders.py)."""
    disk = _get_disk_or_404(session, disk_id)
    try:
        disk_folders.add(session, disk, body.kind, body.relative_path)
    except disk_folders.FolderError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
    session.refresh(disk)
    return DiskResponse.from_model(disk)


@router.delete("/{disk_id}/folders/{folder_id}", response_model=DiskResponse)
def remove_folder(disk_id: int, folder_id: int, session: Session = Depends(get_session)):
    """Toglie la cartella dal disco; sul disco non cambia niente."""
    disk = _get_disk_or_404(session, disk_id)
    if not disk_folders.remove(session, disk, folder_id):
        raise HTTPException(status_code=404, detail=coded_detail("folder_not_found", path=str(folder_id)))
    session.refresh(disk)
    return DiskResponse.from_model(disk)


@router.delete("/{disk_id}", status_code=204)
def delete_disk(disk_id: int, session: Session = Depends(get_session)):
    disk = _get_disk_or_404(session, disk_id)
    session.delete(disk)
    session.commit()
