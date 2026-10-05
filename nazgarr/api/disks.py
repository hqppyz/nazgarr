"""File Browser API scoped-per-disco.

Vedi docs/SPEC.md sezione 4 (ereditata da ratio-guardian). Usata sia per
scegliere le cartelle media e di seeding di un disco (disk_folder,
nazgarr/library/disk_folders.py) che le altre sue cartelle — un solo meccanismo di
scoping condiviso (nazgarr/core/fs_scope.py), mai duplicato.

Nazgarr è un'API JSON pura fin dall'inizio (a differenza di
ratio-guardian, che ha ancora una Web UI Jinja2): anche l'elenco dei mount
disponibili (usato lì solo dalla pagina web) è quindi esposto qui come
endpoint proprio. Il confine dei dischi è disk_scan_root se impostato, se no
le cartelle di dati montate nel container (nazgarr/core/mounts.py).
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nazgarr.core import mounts as container_mounts
from nazgarr.core.errors import CodedError, coded_detail, from_coded_error
from nazgarr.core.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.core.models import ClientTorrentFile, Disk, SeedFile
from nazgarr.library import disk_folders
from nazgarr.web.deps import get_or_404, get_session

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


class DiskCheck(BaseModel):
    code: str
    level: str  # ok | warning | error
    params: dict = {}


class VerifyResponse(BaseModel):
    consistent: bool
    warning: str | None = None  # deprecato: le prove sono in checks
    checks: list[DiskCheck] = []


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
    id: int | None  # None: un disco non ancora migrato (nazgarr/core/db.py migrate_disk_folders)
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


class DetectedMount(BaseModel):
    path: str
    fstype: str
    source: str
    unraid_share: bool
    registered: bool  # già un disco (o dentro uno)


class MountWarning(BaseModel):
    code: str  # split_mounts | share_and_disks | mounts_outside_scan_root
    paths: list[str] = []
    share: list[str] = []
    disks: list[str] = []
    scan_root: str | None = None


class AvailableMountsResponse(BaseModel):
    scan_root: str  # la prima radice: il valore proposto per un disco nuovo
    scan_roots: list[str] = []
    scope_source: str = "default"  # config | mounts | default
    mounts: list[str]  # proposte per un disco nuovo, non ancora registrate
    detected: list[DetectedMount] = []
    warnings: list[MountWarning] = []


class DiskValidationError(CodedError):
    pass


class DiskConflictError(CodedError):
    pass


def _get_disk_or_404(session: Session, disk_id: int) -> Disk:
    return get_or_404(session, Disk, disk_id, "disk_not_found")


def disk_scope(request: Request) -> container_mounts.Scope:
    settings = request.app.state.settings
    own = [settings.data_dir, os.path.dirname(os.path.abspath(os.environ.get("CONFIG_PATH", "config.yaml")))]
    return container_mounts.scope(settings.disk_scan_root, own)


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def list_available_mounts(scope: container_mounts.Scope, used_paths: set[str]) -> list[str]:
    """Le proposte per un disco nuovo, non ancora registrate (né dentro un
    disco): con i mount rilevati, i mount stessi; con una radice
    configurata, le sue sottocartelle di primo livello (i bind mount dei
    dischi fisici sotto /mnt, come prima)."""
    used_real = [os.path.realpath(p) for p in used_paths]
    if scope.source == "mounts":
        candidates = [m.mount_point for m in scope.mounts]
    else:
        candidates = [entry.path for root in scope.roots if os.path.isdir(root)
                      for entry in os.scandir(root) if entry.is_dir()]
    return sorted(c for c in candidates
                  if not any(_inside(os.path.realpath(c), used) for used in used_real))


def create_disk(session: Session, label: str, root_path: str, scope: container_mounts.Scope) -> Disk:
    if not os.path.isdir(root_path):
        raise DiskValidationError("disk_root_path_not_a_directory", path=root_path)
    if not scope.contains(root_path):
        raise DiskValidationError("disk_root_path_outside_scan_root", scan_root=", ".join(scope.roots))
    # Un disco dentro un altro (o che ne contiene uno): gli stessi file contati due volte.
    real = os.path.realpath(root_path)
    for other in session.query(Disk).all():
        other_real = os.path.realpath(other.root_path)
        if real != other_real and (_inside(real, other_real) or _inside(other_real, real)):
            raise DiskValidationError("disk_root_nested", path=root_path, other=other.label)
    disk = Disk(label=label, root_path=root_path)
    session.add(disk)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DiskConflictError("disk_root_path_conflict", path=root_path) from exc
    return disk


def verify_disk(session: Session, disk: Disk) -> VerifyResponse:
    """La prova del disco (nazgarr/library/disk_folders.py test_disk): cartelle,
    filesystem e un hardlink di prova fra le cartelle. st_dev da solo non
    basta: su FUSE cambia a ogni rimontaggio."""
    result = disk_folders.test_disk(session, disk)
    if result["checks"] and result["checks"][0]["code"] == "disk_unreachable":
        raise HTTPException(status_code=404, detail=coded_detail("disk_root_path_unreachable", path=disk.root_path))
    problems = [c for c in result["checks"] if c["level"] != "ok"]
    return VerifyResponse(
        consistent=result["ok"],
        warning=", ".join(c["code"] for c in problems) or None,
        checks=[DiskCheck(**c) for c in result["checks"]],
    )


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
    scope = disk_scope(request)
    used_paths = {d.root_path for d in session.query(Disk).all()}
    used_real = [os.path.realpath(p) for p in used_paths]
    return AvailableMountsResponse(
        scan_root=scope.roots[0], scan_roots=scope.roots, scope_source=scope.source,
        mounts=list_available_mounts(scope, used_paths),
        detected=[
            DetectedMount(path=m.mount_point, fstype=m.fstype, source=m.source, unraid_share=m.is_unraid_share,
                          registered=any(_inside(os.path.realpath(m.mount_point), u) for u in used_real))
            for m in scope.mounts
        ],
        warnings=[MountWarning(**w) for w in scope.warnings],
    )


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
        disk = create_disk(session, body.label, body.root_path, disk_scope(request))
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
        if body.new_torrent_rel_path is not None:
            disk.new_torrent_rel_path = (disk_folders.validate_target(disk, body.new_torrent_rel_path)
                                         if body.new_torrent_rel_path else None)
        if body.upload_rel_path is not None:
            disk.upload_rel_path = (disk_folders.validate_target(disk, body.upload_rel_path)
                                    if body.upload_rel_path else None)
    except disk_folders.FolderError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc
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
    """Una cartella media o di seeding in più (nazgarr/library/disk_folders.py)."""
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
