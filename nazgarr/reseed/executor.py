"""Esecutore: hardlink + aggiunta al client (direzione media_to_torrent)
o solo aggiunta al client (direzione torrent_to_client, il file esiste
già) — sempre con recheck forzato, mai skip_checking (docs/SPEC.md
sezione 8). Ordine dei passi per media_to_torrent, mai bypassabile:
1. verifica st_dev sorgente/destinazione (mai un cross-device silente)
2. hardlink col nome esatto atteso dal tracker
3. add_torrent sul client, sempre con force_recheck=True

Un candidato con righe candidate_file (nazgarr/torrents/layout.py: film con
extra, season pack) si ricrea file per file: un hardlink per ogni file del
torrent che ha un file locale, video ed extra; gli extra senza file locale
li scarica il client dopo il recheck, entro seed_job.expected_missing_bytes.
Un video senza file locale non arriva mai qui (candidato a confidence 0).
I candidati salvati prima di candidate_file seguono il percorso a file
singolo originale. Porting/adattamento da ratio-guardian/app/executor.py,
per le due direzioni di docs/SPEC.md sezione 3.

Il client riceve sempre i byte del .torrent scaricato qui dal tracker,
mai il download_link (audit 2026-10-18): con il link il client scaricava
la sua copia, e niente la legava a quella che il matching e il controllo
completo avevano verificato. L'info hash di quei byte deve essere quello
del candidato (scritto dal matching o dal controllo completo), ed è
quello che il client deve far comparire.
"""

import json
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from nazgarr.adapters.torrent_client.base import (
    CONTENT_LAYOUTS,
    TorrentAddTimeoutError,
    TorrentAlreadyInClientError,
    TorrentClientAdapter,
    is_stopped_state,
    layout_kwargs,
)
from nazgarr.core import settings_repo
from nazgarr.core.errors import CodedError, english
from nazgarr.core.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.core.logs import safe_error
from nazgarr.core.models import Candidate, Disk, DiskTorrentClient, MatchReview, SeedJob, TorrentClient
from nazgarr.integrations import adapter_factory
from nazgarr.library import hardlinks
from nazgarr.library.tmdb_client import TMDBClient
from nazgarr.reseed import download_links
from nazgarr.torrents import client_labels, client_paths
from nazgarr.torrents.layout import expected_missing_bytes
from nazgarr.torrents.metainfo import TorrentMetainfoError, compute_info_hash, parse_torrent_info

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Errore esplicito che impedisce l'esecuzione — mai un fallimento silente."""


def _error_text(exc: Exception) -> str:
    """Il messaggio salvato sul seed_job e mostrato nella pagina Reseeding:
    per un errore con codice il suo testo inglese con i parametri (prima
    solo il codice, es. "client_cannot_see_path" senza dire quale percorso)."""
    return english(exc.code, exc.params) if isinstance(exc, CodedError) else str(exc)


def client_visible_path(session: Session, disk: Disk, torrent_client_id: int | None, local_path: str) -> str:
    """Traduce un path lato Nazgarr nel path equivalente visto DA QUESTO
    client torrent, quando i due girano in container/mount diversi per lo
    stesso disco fisico (disk_torrent_client: torrent_client_root_path e
    local_rel_path per la coppia (disk, torrent_client_id), nazgarr/torrents/client_paths.py).
    Senza mappatura, client e Nazgarr vedono lo stesso path. Un path che il
    client non vede (fuori dalla sottocartella mappata): ClientPathError."""
    if torrent_client_id is None:
        return local_path
    link = (
        session.query(DiskTorrentClient)
        .filter_by(disk_id=disk.id, torrent_client_id=torrent_client_id)
        .one_or_none()
    )
    if link is None:
        return local_path
    return client_paths.to_client(
        client_paths.Mapping(disk.root_path, link.torrent_client_root_path, link.local_rel_path), local_path)


FetchTorrent = Callable[[Candidate], bytes]


def execute_review(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False, fetch_torrent: FetchTorrent | None = None,
) -> SeedJob:
    """skip_recheck: SOLO dopo un controllo completo di Nazgarr al 100% senza
    extra mancanti, con l'opzione accesa dall'utente (nazgarr/reseed/review.py). In ogni
    altro caso il client fa il suo recheck reale, come sempre.
    fetch_torrent: i byte del .torrent del candidato (default: dal suo
    tracker, _download_torrent)."""
    candidate = review.candidate
    if candidate.files:
        if candidate.direction == "media_to_torrent":
            return _execute_layout_media_to_torrent(
                session, review, adapter, torrent_client_id, skip_recheck, fetch_torrent)
        return _execute_layout_torrent_to_client(
            session, review, adapter, torrent_client_id, skip_recheck, fetch_torrent)
    if candidate.direction == "media_to_torrent":
        return _execute_media_to_torrent(session, review, adapter, torrent_client_id, skip_recheck, fetch_torrent)
    return _execute_torrent_to_client(session, review, adapter, torrent_client_id, skip_recheck, fetch_torrent)


@dataclass(frozen=True)
class _CheckedTorrent:
    content: bytes
    info_hash: str  # minuscolo


def _download_torrent(candidate: Candidate) -> bytes:
    """Il .torrent del candidato dal suo tracker, con il rate limit, la
    regola dell'host e il tetto di dimensione dell'adapter
    (Unit3dTrackerAdapter.download_torrent)."""
    tracker = candidate.tracker
    if tracker is None:
        raise ExecutionError("The candidate's tracker no longer exists: its .torrent cannot be downloaded")
    try:
        with adapter_factory.tracker(tracker) as tracker_adapter:
            return download_links.download(tracker_adapter, candidate)  # la chiave rimessa qui
    except Exception as exc:
        raise ExecutionError(f"Could not download the .torrent from {tracker.label}: {safe_error(exc)}") from exc


def _torrent_to_add(session: Session, candidate: Candidate, fetch_torrent: FetchTorrent | None) -> _CheckedTorrent:
    """I byte che il client riceverà, scaricati da Nazgarr e legati al
    candidato: se il matching o il controllo completo ne conoscono l'info
    hash, deve essere quello (un tracker che serve un torrent diverso a
    questa richiesta non ottiene niente); altrimenti è quello di questi
    byte, e si scrive sul candidato per l'attesa del client e i retry."""
    content = (fetch_torrent or _download_torrent)(candidate)
    try:
        parse_torrent_info(content)
        info_hash = compute_info_hash(content)
    except TorrentMetainfoError as exc:
        raise ExecutionError(f"The tracker sent an invalid .torrent: {exc}") from exc
    expected = (candidate.info_hash or "").lower()
    if expected and expected != info_hash:
        raise ExecutionError(
            f"The tracker sent a different .torrent (info hash {info_hash}) from the one that was matched "
            f"and checked ({expected}): nothing added. Delete this execution so the next scan matches it again"
        )
    if not expected:
        candidate.info_hash = info_hash
        session.commit()
    return _CheckedTorrent(content=content, info_hash=info_hash)


def _labels(session: Session, torrent_client_id: int | None, candidate, review: MatchReview | None = None) -> dict:
    """Categoria (per tipo di contenuto) e tag per i reseed del client
    (nazgarr/torrents/client_labels.py). TMDB, per sapere se è un anime, solo se il
    client ha una categoria per gli anime; senza TMDB non lo è. Quelli scelti
    a mano sulla review vincono (NULL = default, "" = nessuno)."""
    client = session.get(TorrentClient, torrent_client_id) if torrent_client_id is not None else None
    if client is None:
        return {}
    chosen_category = review.client_category if review is not None else None
    chosen_tags = review.client_tags if review is not None else None
    tags = chosen_tags if chosen_tags is not None else client_labels.default_tags(client, "reseed")
    if chosen_category is not None:
        return client_labels.add_kwargs(chosen_category or None, tags)
    item = candidate.media_item
    content_type = item.content_type if item is not None else None
    anime = False
    if client.category_anime and item is not None and item.tmdb_id:
        api_key = settings_repo.get_setting(session, "tmdb_api_key")
        try:
            anime = bool(api_key) and client_labels.is_anime(
                TMDBClient(api_key=api_key).full_details(content_type, item.tmdb_id)
            )
        except Exception:
            logger.warning("TMDB non disponibile per il riconoscimento anime di %s", item.tmdb_id, exc_info=True)
    return client_labels.add_kwargs(client_labels.default_category(client, content_type, anime), tags)


def _add_to_client(
    adapter: TorrentClientAdapter, torrent: _CheckedTorrent, save_path: str, seed_job: SeedJob, skip_recheck: bool,
    labels: dict | None = None, layout: str = "Original",
) -> str:
    """Aggiunge il torrent al client. Il recheck del client si salta solo se
    il chiamante l'ha verificato lui stesso al 100% (skip_recheck): resta
    scritto sul seed_job, così si vede quali esecuzioni sono passate così.
    labels: categoria e tag del client (_labels), solo se ce ne sono.
    Un client che non sa saltarlo (can_skip_recheck) lo fa comunque.
    layout: sempre esplicito (_Placement), "Original" per file già al loro
    posto: la preferenza del client non li deve spostare.

    Il .torrent va come file locale temporaneo, che ogni adapter manda al
    client col suo contenuto (docs/SDK.md): mai il link del tracker."""
    skip_recheck = skip_recheck and getattr(adapter, "can_skip_recheck", True)
    extra = {"skip_check_verified": True} if skip_recheck else {}
    with tempfile.TemporaryDirectory(prefix="nazgarr-reseed-") as folder:
        path = os.path.join(folder, f"{torrent.info_hash}.torrent")
        with open(path, "wb") as fh:
            fh.write(torrent.content)
        info_hash = adapter.add_torrent(
            path, save_path=save_path, force_recheck=True,
            expected_info_hash=torrent.info_hash, **extra, **(labels or {}), **layout_kwargs(adapter, layout),
        )
    seed_job.recheck_skipped = skip_recheck or None
    return info_hash


def _adopt_after_add_error(
    session: Session, adapter: TorrentClientAdapter, candidate, seed_job: SeedJob, exc: Exception,
) -> str:
    """Dopo un errore di add_torrent, cosa sa il client del torrent:
    "adopted" se ce l'ha (il client l'ha accettato e poi qualcosa è andato
    storto, tipicamente l'attesa del suo hash scaduta mentre scaricava il
    .torrent dal tracker): il seed_job lo segue come un'aggiunta riuscita;
    "absent" se il client risponde e non ce l'ha; "unknown" se non si può
    sapere. Prima gli hardlink si toglievano a ogni errore: il torrent
    arrivava lo stesso, non trovava i file e partiva in download."""
    if isinstance(exc, TorrentAlreadyInClientError) or not candidate.info_hash:
        return "absent" if isinstance(exc, TorrentAlreadyInClientError) else "unknown"
    try:
        info = adapter.get_torrent_info(candidate.info_hash)
    except Exception:
        logger.warning("Impossibile chiedere al client se ha %s dopo l'errore", candidate.info_hash, exc_info=True)
        return "unknown"
    if info is None:
        return "absent"
    logger.warning(
        "Il client ha il torrent %s nonostante l'errore (%s): seed job %s lo segue",
        info.info_hash, _error_text(exc), seed_job.id,
    )
    if not seed_job.recheck_skipped:
        try:  # l'errore può essere arrivato prima del recheck forzato
            adapter.recheck(info.info_hash)
        except Exception:
            logger.warning("Recheck di %s non richiesto al client", info.info_hash, exc_info=True)
    seed_job.info_hash = info.info_hash
    seed_job.torrent_added_at = datetime.now(UTC)
    seed_job.recheck_status = "pending"
    session.commit()
    return "adopted"


@dataclass(frozen=True)
class _Placement:
    """Dove vanno i nuovi hardlink perché il torrent li trovi rispettando
    il layout del contenuto scelto dall'utente nel client (qBittorrent:
    Opzioni › Download): save_dir è la cartella di save_path dentro la
    cartella dei nuovi torrent, folder la cartella radice dei file dentro
    save_dir, layout quello da mandare al client."""

    save_dir: str | None
    folder: str | None
    layout: str

    def rel_path(self, torrent_path: str) -> str:
        return "/".join(p for p in (self.save_dir, self.folder, torrent_path) if p)


def _client_layout(adapter: TorrentClientAdapter) -> str:
    try:
        layout = adapter.content_layout()
    except AttributeError:
        return "Original"  # un adapter senza content_layout segue il .torrent
    except Exception:
        logger.warning("Layout del contenuto del client non letto: uso Original", exc_info=True)
        return "Original"
    return layout if layout in CONTENT_LAYOUTS else "Original"


def _placement(adapter: TorrentClientAdapter, candidate, single_file_name: str | None) -> _Placement:
    """"Crea sottocartella" su un torrent a file singolo: la cartella col
    nome del file senza estensione la crea Nazgarr, e il torrent arriva con
    save_path lì dentro e layout Original, così non serve indovinare come
    il client sceglie quel nome. "Non creare sottocartella" su un torrent
    con la cartella radice: gli hardlink senza quella cartella, e il client
    riceve lo stesso layout. Negli altri casi il layout non cambia niente."""
    layout = _client_layout(adapter)
    if layout == "Subfolder" and not candidate.folder and single_file_name:
        stem = os.path.splitext(single_file_name)[0] or single_file_name
        return _Placement(save_dir=stem, folder=None, layout="Original")
    if layout == "NoSubfolder" and candidate.folder:
        return _Placement(save_dir=None, folder=None, layout="NoSubfolder")
    return _Placement(save_dir=None, folder=candidate.folder, layout="Original")


def _torrent_rel_path(candidate, torrent_path: str) -> str:
    return f"{candidate.folder}/{torrent_path}" if candidate.folder else torrent_path


def _missing_bytes_for(candidate) -> int:
    missing = [f for f in candidate.files if not f.is_video and f.media_file_id is None and f.seed_file_id is None]
    return expected_missing_bytes(sum(f.size_bytes or 0 for f in missing), len(missing), candidate.piece_length)


def _require_known_structure(candidate) -> None:
    """Un torrent con più file ha sempre una cartella radice (info.name):
    senza, i file finirebbero sciolti nella cartella dei torrent e il
    recheck non potrebbe mai riuscire. Candidati salvati prima che la
    struttura venisse letta dal .torrent: vanno ricercati ("Cerca ora")."""
    if len(candidate.files) > 1 and not candidate.folder:
        raise ExecutionError(
            "The torrent's folder is unknown for this multi-file candidate: search it again (Search now) "
            "to read its real structure from the .torrent"
        )


def _require_every_video(candidate) -> None:
    for f in candidate.files:
        if f.is_video and f.media_file_id is None and f.seed_file_id is None:
            raise ExecutionError(
                f"Video '{f.torrent_path}' of the torrent has no local file: a partial pack is never executed"
            )


def _source_path(disk: Disk, relative_path: str) -> str:
    """Il file in libreria da cui nasce l'hardlink: dentro il disco
    (fs_scope) e un file vero, non un link simbolico. Lo scanner salta i
    symlink, ma fra la scansione e l'esecuzione il file può cambiare."""
    try:
        path = resolve_scoped(disk.root_path, relative_path)
    except ScopeViolation as exc:
        raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc
    if os.path.islink(os.path.join(disk.root_path, relative_path)) or os.path.islink(path):
        raise ExecutionError(f"Local file is a symbolic link: {path}")
    if not os.path.isfile(path):
        raise ExecutionError(f"Local file not found: {path}")
    return path


def _check_link(source_path: str, target_path: str, target_root: str) -> bool:
    """I controlli comuni (nazgarr/library/hardlinks.py::check_link) prima di creare
    un hardlink. True se la destinazione è già lo stesso file (stesso inode):
    un cross-seed della stessa release con lo stesso nome su un altro
    tracker riusa quell'hardlink. Un altro file al suo posto resta un
    errore: mai sovrascritto."""
    try:
        return hardlinks.check_link(source_path, target_path, target_root) is None
    except hardlinks.LinkProblem as problem:
        if problem.code == "cross_device":
            raise ExecutionError(
                f"Source and destination are on different devices ({problem.detail}): "
                "a hardlink cannot cross filesystems, see docs/SPEC.md section 4"
            ) from problem
        if problem.code == "target_exists":
            raise ExecutionError(f"Destination path already exists: {target_path}") from problem
        raise ExecutionError(f"Local file is not a regular file: {problem.path}") from problem
    except ScopeViolation as exc:
        raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc


def _seed(
    session: Session, seed_job: SeedJob, review: MatchReview, adapter: TorrentClientAdapter,
    torrent_client_id: int | None, disk: Disk, save_root: str, skip_recheck: bool,
    fetch_torrent: FetchTorrent | None, links: list[tuple[str, str]] | None = None, layout: str = "Original",
) -> SeedJob:
    """La parte comune a ogni esecuzione, dopo i controlli: il .torrent dal
    tracker, gli hardlink (links: None per torrent -> client, dove i file
    ci sono già), l'aggiunta al client. Un'unica regola sugli errori, prima
    copiata quattro volte con differenze (audit 2026-10-18): se il client ha
    il torrent lo si segue; se risponde che non ce l'ha, si tolgono solo gli
    hardlink appena creati da questa esecuzione (i file in libreria non si
    toccano mai), tranne dopo un timeout, quando potrebbe ancora arrivare e
    senza i file partirebbe in download."""
    candidate = review.candidate
    created: list[str] = []
    add_sent = False
    try:
        torrent = _torrent_to_add(session, candidate, fetch_torrent)  # prima di ogni hardlink
        if links is not None:
            created = hardlinks.create_links(links)  # se uno fallisce, toglie quelli appena creati
            seed_job.hardlink_created_at = datetime.now(UTC)
            session.commit()
            logger.info("Creati %d hardlink per candidate %s (%d già al loro posto)",
                        len(created), candidate.id, len(links) - len(created))
        client_save_path = client_visible_path(session, disk, torrent_client_id, save_root)
        labels = _labels(session, torrent_client_id, candidate, review)
        add_sent = True
        info_hash = _add_to_client(adapter, torrent, client_save_path, seed_job, skip_recheck, labels, layout)
        seed_job.info_hash = info_hash
        seed_job.torrent_added_at = datetime.now(UTC)
        seed_job.recheck_status = "pending"
        session.commit()
        logger.info("Torrent aggiunto al client (info_hash=%s), recheck in corso", info_hash)
    except Exception as exc:
        known = _adopt_after_add_error(session, adapter, candidate, seed_job, exc) if add_sent else "absent"
        if known == "adopted":
            return seed_job
        if known == "absent" and not isinstance(exc, TorrentAddTimeoutError):
            hardlinks.remove_links(created)
        elif created:
            logger.warning("Hardlink di candidate %s lasciati al loro posto: il client potrebbe avere il torrent",
                           candidate.id)
        seed_job.final_status = "failed"
        seed_job.error_message = _error_text(exc)
        session.commit()
        raise ExecutionError(str(exc)) from exc
    return seed_job


def _require_download_link(candidate) -> None:
    if not candidate.download_link:
        raise ExecutionError("Candidate has no download_link: cannot add the torrent to the client")


def _new_seed_job(session: Session, candidate, torrent_client_id: int | None, **source) -> SeedJob:
    seed_job = SeedJob(
        candidate_id=candidate.id, final_status="in_progress", torrent_client_id=torrent_client_id,
        expected_missing_bytes=_missing_bytes_for(candidate) if candidate.files else None, **source,
    )
    session.add(seed_job)
    session.commit()
    return seed_job


def _scoped_file(disk: Disk, relative_path: str) -> str:
    """Un file già su disco che il torrent userà così com'è (torrent ->
    client): dentro il disco (fs_scope) ed esistente."""
    try:
        path = resolve_scoped(disk.root_path, relative_path)
    except ScopeViolation as exc:
        raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc
    if not os.path.isfile(path):
        raise ExecutionError(f"Local file not found: {relative_path}")
    return path


def _new_torrents_root(disk: Disk) -> str:
    if not disk.seeding_folders:
        raise ExecutionError(f"Disk '{disk.label}' has no seeding folder configured")
    try:
        target_root = resolve_scoped(disk.root_path, disk.effective_new_torrent_rel_path)
    except ScopeViolation as exc:
        raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc
    if not os.path.isdir(target_root):
        raise ExecutionError(f"Destination folder for new hardlinks not found: {target_root}")
    return target_root


def _in_scope(root: str, relative: str) -> str:
    try:
        return resolve_scoped(root, relative)
    except ScopeViolation as exc:
        raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc


def _execute_layout_media_to_torrent(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False, fetch_torrent: FetchTorrent | None = None,
) -> SeedJob:
    """Ricrea il torrent intero con hardlink dai file in libreria. Tutti i
    controlli PRIMA di creare il primo hardlink (scope, stesso disco, stesso
    filesystem, destinazioni libere): mai un pack ricreato a metà per un
    problema che si poteva vedere prima."""
    candidate = review.candidate
    anchor = review.media_file
    if anchor is None:
        raise ExecutionError(f"MatchReview {review.id} (media_to_torrent) has no linked media_file")
    _require_known_structure(candidate)
    _require_every_video(candidate)
    disk = anchor.disk
    target_root = _new_torrents_root(disk)

    placement = _placement(adapter, candidate, candidate.files[0].torrent_path if len(candidate.files) == 1 else None)
    links: list[tuple[str, str]] = []
    for f in candidate.files:
        if f.media_file is None:
            continue  # extra senza file locale: lo scarica il client
        if f.media_file.disk_id != disk.id:
            raise ExecutionError(f"'{f.media_file.relative_path}' is on another disk: a hardlink cannot cross disks")
        source_path = _source_path(disk, f.media_file.relative_path)
        target_path = _in_scope(target_root, placement.rel_path(f.torrent_path))
        if _check_link(source_path, target_path, target_root):
            continue  # già lì, stesso inode: niente da creare (e niente da togliere se fallisce)
        links.append((source_path, target_path))
    _require_download_link(candidate)
    save_root = _in_scope(target_root, placement.save_dir) if placement.save_dir else target_root

    seed_job = _new_seed_job(session, candidate, torrent_client_id, source_media_file_id=anchor.id)
    return _seed(session, seed_job, review, adapter, torrent_client_id, disk, save_root, skip_recheck,
                 fetch_torrent, links=links, layout=placement.layout)


def _execute_layout_torrent_to_client(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False, fetch_torrent: FetchTorrent | None = None,
) -> SeedJob:
    """La cartella del torrent è ancora su disco: nessun hardlink, solo
    l'aggiunta al client con save_path = la cartella che la contiene,
    ricavata dall'anchor e verificata su ogni altro file abbinato."""
    candidate = review.candidate
    anchor = review.seed_file
    if anchor is None:
        raise ExecutionError(f"MatchReview {review.id} (torrent_to_client) has no linked seed_file")
    _require_known_structure(candidate)
    _require_every_video(candidate)
    _require_download_link(candidate)
    disk = anchor.disk

    anchor_row = next((f for f in candidate.files if f.seed_file_id == anchor.id), None)
    if anchor_row is None:
        raise ExecutionError(f"Seed file {anchor.id} is not part of candidate {candidate.id}")
    suffix = _torrent_rel_path(candidate, anchor_row.torrent_path)
    if not anchor.relative_path.endswith(suffix):
        raise ExecutionError(f"'{anchor.relative_path}' does not end with the torrent path '{suffix}'")
    root_rel = anchor.relative_path[: -len(suffix)].rstrip("/")
    for f in candidate.files:
        if f.seed_file is None:
            continue
        expected = f"{root_rel}/{_torrent_rel_path(candidate, f.torrent_path)}" if root_rel else \
            _torrent_rel_path(candidate, f.torrent_path)
        if f.seed_file.disk_id != disk.id or f.seed_file.relative_path != expected:
            raise ExecutionError(f"'{f.seed_file.relative_path}' is not where the torrent expects it ({expected})")
        _scoped_file(disk, f.seed_file.relative_path)
    save_path_local = _in_scope(disk.root_path, root_rel) if root_rel else disk.root_path

    seed_job = _new_seed_job(session, candidate, torrent_client_id, source_seed_file_id=anchor.id)
    return _seed(session, seed_job, review, adapter, torrent_client_id, disk, save_path_local, skip_recheck,
                 fetch_torrent)


def _execute_media_to_torrent(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False, fetch_torrent: FetchTorrent | None = None,
) -> SeedJob:
    """Candidato a file singolo salvato prima delle righe candidate_file."""
    candidate = review.candidate
    media_file = review.media_file
    if media_file is None:
        raise ExecutionError(f"MatchReview {review.id} (media_to_torrent) has no linked media_file")
    disk = media_file.disk
    target_root = _new_torrents_root(disk)
    source_path = _source_path(disk, media_file.relative_path)

    file_list = json.loads(candidate.file_list_json) if candidate.file_list_json else []
    expected_filename = file_list[0] if file_list else os.path.basename(source_path)
    # Un torrent a file singolo può comunque avere una cartella contenitore
    # (candidate.folder) — molte release la usano anche per i film.
    placement = _placement(adapter, candidate, expected_filename)
    target_path = _in_scope(target_root, placement.rel_path(expected_filename))
    save_root = _in_scope(target_root, placement.save_dir) if placement.save_dir else target_root
    reuse = _check_link(source_path, target_path, target_root)  # già lì, stesso inode: un cross-seed
    _require_download_link(candidate)

    seed_job = _new_seed_job(session, candidate, torrent_client_id, source_media_file_id=media_file.id)
    return _seed(session, seed_job, review, adapter, torrent_client_id, disk, save_root, skip_recheck,
                 fetch_torrent, links=[] if reuse else [(source_path, target_path)], layout=placement.layout)


def _execute_torrent_to_client(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False, fetch_torrent: FetchTorrent | None = None,
) -> SeedJob:
    """Il file è già presente sul filesystem (docs/SPEC.md sezione 3): mai
    un nuovo hardlink, solo l'aggiunta al client puntando alla cartella che
    già lo contiene. Candidato a file singolo salvato prima delle righe
    candidate_file."""
    candidate = review.candidate
    seed_file = review.seed_file
    if seed_file is None:
        raise ExecutionError(f"MatchReview {review.id} (torrent_to_client) has no linked seed_file")
    disk = seed_file.disk
    _require_download_link(candidate)
    _scoped_file(disk, seed_file.relative_path)
    # La cartella com'è scritta (non quella risolta dai link simbolici): è
    # quella che il client vede, tradotta da client_visible_path.
    save_path_local = os.path.dirname(os.path.join(disk.root_path, seed_file.relative_path))

    seed_job = _new_seed_job(session, candidate, torrent_client_id, source_seed_file_id=seed_file.id)
    return _seed(session, seed_job, review, adapter, torrent_client_id, disk, save_path_local, skip_recheck,
                 fetch_torrent)


def reconcile_seed_job(session: Session, seed_job: SeedJob, adapter: TorrentClientAdapter) -> SeedJob:
    """Aggiorna recheck_status/final_status interrogando lo stato reale nel
    client. Il recheck è asincrono lato client: va richiamata finché non
    raggiunge uno stato definitivo (mai un'attesa bloccante qui dentro)."""
    if seed_job.info_hash is None:
        raise ExecutionError(f"SeedJob {seed_job.id} does not have an info_hash yet")

    status = adapter.get_torrent_status(seed_job.info_hash)
    recheck_status = status.recheck_status
    allowed = seed_job.expected_missing_bytes or 0
    if (
        recheck_status == "failed" and status.incomplete and allowed > 0
        and status.amount_left is not None and status.amount_left <= allowed
    ):
        # Recheck finito e mancano solo i file extra che si sapeva di non
        # avere (nfo, sottotitoli, sample): il client li sta scaricando.
        recheck_status = "ok"
        logger.info(
            "Seed_job %s: recheck ok, il client scarica %d byte di file extra mancanti",
            seed_job.id, status.amount_left,
        )
    seed_job.recheck_status = recheck_status
    if recheck_status == "ok" and is_stopped_state(status.state):
        # Recheck riuscito ma fermo: la condizione di arresto "file
        # controllati" del client (qui non la lascia cambiare all'aggiunta).
        try:
            adapter.start(seed_job.info_hash)
            logger.info("Seed_job %s: torrent fermo dopo il recheck, avviato", seed_job.id)
        except Exception:
            logger.warning("Seed_job %s: torrent fermo dopo il recheck, avvio fallito", seed_job.id, exc_info=True)
    if recheck_status == "ok":
        seed_job.final_status = "seeding"
        logger.info("Recheck ok, seed_job %s in seeding (info_hash=%s)", seed_job.id, seed_job.info_hash)
    elif recheck_status == "failed":
        seed_job.final_status = "failed"
        seed_job.error_message = f"Recheck failed, client state: {status.state}" + _stop_after_failed_recheck(
            adapter, seed_job, status.state)
        logger.warning("Recheck fallito per seed_job %s: stato client %s", seed_job.id, status.state)
    session.commit()
    return seed_job


def _stop_after_failed_recheck(adapter: TorrentClientAdapter, seed_job: SeedJob, state: str | None) -> str:
    """Un reseed col recheck fallito si ferma nel client (audit 2026-10-18):
    avviato, scaricherebbe i piece che mancano scrivendoli nei file a
    save_path, che sono hardlink dei file in libreria (gli stessi byte), o
    i file già nella cartella dei torrent. Niente di approvato dall'utente.
    Ritorna la coda del messaggio del seed job. Un retry che trova il
    recheck riuscito lo riavvia (il ramo "fermo dopo il recheck" sopra)."""
    if is_stopped_state(state):
        return ""
    try:
        adapter.stop(seed_job.info_hash)
    except NotImplementedError:
        logger.warning("Seed_job %s: il client non sa fermare il torrent %s", seed_job.id, seed_job.info_hash)
        return "; this client cannot be told to stop it: stop it by hand, or it downloads into the linked files"
    except Exception:
        logger.warning("Seed_job %s: torrent %s non fermato", seed_job.id, seed_job.info_hash, exc_info=True)
        return "; it could not be stopped in the client: stop it by hand, or it downloads into the linked files"
    logger.info("Seed_job %s: torrent %s fermato dopo il recheck fallito", seed_job.id, seed_job.info_hash)
    return "; stopped in the client so it does not download into the linked files"


def retry_seed_job(
    session: Session, seed_job: SeedJob, adapter: TorrentClientAdapter, torrent_client_id: int | None = None
) -> SeedJob:
    """Ritenta un seed_job failed. Se ha già un info_hash, il problema era
    probabilmente solo il recheck mai confermato: si reinterroga il client
    invece di ripartire da zero (un torrent fermato dopo un recheck fallito
    riparte se ora il recheck è riuscito). Da zero, gli hardlink già al loro
    posto con lo stesso inode si riusano, e il .torrent si riscarica e si
    ricontrolla contro l'info hash del candidato."""
    if seed_job.final_status != "failed":
        raise ExecutionError(f"SeedJob {seed_job.id} is not in failed status (current: {seed_job.final_status})")
    if seed_job.info_hash:
        logger.info("Retry seed_job %s: info_hash già presente, reinterrogo il client", seed_job.id)
        seed_job.final_status = "in_progress"
        session.commit()
        return reconcile_seed_job(session, seed_job, adapter)
    candidate = session.get(Candidate, seed_job.candidate_id)
    if candidate is not None and candidate.info_hash:
        try:  # l'aggiunta fallita può essere arrivata al client lo stesso
            info = adapter.get_torrent_info(candidate.info_hash)
        except Exception:
            info = None
        if info is not None:
            logger.info("Retry seed_job %s: il client ha già il torrent %s, lo seguo", seed_job.id, info.info_hash)
            seed_job.info_hash = info.info_hash
            seed_job.torrent_added_at = seed_job.torrent_added_at or datetime.now(UTC)
            seed_job.final_status = "in_progress"
            seed_job.recheck_status = "pending"
            session.commit()
            return reconcile_seed_job(session, seed_job, adapter)

    review = (
        session.query(MatchReview)
        .filter(MatchReview.candidate_id == seed_job.candidate_id)
        .filter(
            (MatchReview.media_file_id == seed_job.source_media_file_id)
            if seed_job.source_media_file_id is not None
            else (MatchReview.seed_file_id == seed_job.source_seed_file_id)
        )
        .one()
    )
    logger.info("Retry seed_job %s: riparto da zero (nessun info_hash mai ottenuto)", seed_job.id)
    return execute_review(session, review, adapter, torrent_client_id)
