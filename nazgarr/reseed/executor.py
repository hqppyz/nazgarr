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
"""

import json
import logging
import os
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
from nazgarr.core.models import Candidate, Disk, DiskTorrentClient, MatchReview, SeedJob, TorrentClient
from nazgarr.library import hardlinks
from nazgarr.library.tmdb_client import TMDBClient
from nazgarr.torrents import client_labels, client_paths
from nazgarr.torrents.layout import expected_missing_bytes

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


def execute_review(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False,
) -> SeedJob:
    """skip_recheck: SOLO dopo un controllo completo di Nazgarr al 100% senza
    extra mancanti, con l'opzione accesa dall'utente (nazgarr/reseed/review.py). In ogni
    altro caso il client fa il suo recheck reale, come sempre."""
    candidate = review.candidate
    if candidate.files:
        if candidate.direction == "media_to_torrent":
            return _execute_layout_media_to_torrent(session, review, adapter, torrent_client_id, skip_recheck)
        return _execute_layout_torrent_to_client(session, review, adapter, torrent_client_id, skip_recheck)
    if candidate.direction == "media_to_torrent":
        return _execute_media_to_torrent(session, review, adapter, torrent_client_id, skip_recheck)
    return _execute_torrent_to_client(session, review, adapter, torrent_client_id, skip_recheck)


def _labels(session: Session, torrent_client_id: int | None, candidate) -> dict:
    """Categoria (per tipo di contenuto) e tag per i reseed del client
    (nazgarr/torrents/client_labels.py). TMDB, per sapere se è un anime, solo se il
    client ha una categoria per gli anime; senza TMDB non lo è."""
    client = session.get(TorrentClient, torrent_client_id) if torrent_client_id is not None else None
    if client is None:
        return {}
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
    return client_labels.add_kwargs(
        client_labels.default_category(client, content_type, anime), client_labels.default_tags(client, "reseed"),
    )


def _add_to_client(
    adapter: TorrentClientAdapter, candidate, save_path: str, seed_job: SeedJob, skip_recheck: bool,
    labels: dict | None = None, layout: str = "Original",
) -> str:
    """Aggiunge il torrent al client. Il recheck del client si salta solo se
    il chiamante l'ha verificato lui stesso al 100% (skip_recheck): resta
    scritto sul seed_job, così si vede quali esecuzioni sono passate così.
    labels: categoria e tag del client (_labels), solo se ce ne sono.
    Un client che non sa saltarlo (can_skip_recheck) lo fa comunque.
    layout: sempre esplicito (_Placement), "Original" per file già al loro
    posto: la preferenza del client non li deve spostare."""
    skip_recheck = skip_recheck and getattr(adapter, "can_skip_recheck", True)
    extra = {"skip_check_verified": True} if skip_recheck else {}
    info_hash = adapter.add_torrent(
        candidate.download_link, save_path=save_path, force_recheck=True,
        expected_info_hash=candidate.info_hash, **extra, **(labels or {}), **layout_kwargs(adapter, layout),
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


def _execute_layout_media_to_torrent(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False,
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
    if not disk.seeding_folders:
        raise ExecutionError(f"Disk '{disk.label}' has no seeding folder configured")
    try:
        target_root = resolve_scoped(disk.root_path, disk.effective_new_torrent_rel_path)
    except ScopeViolation as exc:
        raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc
    if not os.path.isdir(target_root):
        raise ExecutionError(f"Destination folder for new hardlinks not found: {target_root}")

    placement = _placement(adapter, candidate, candidate.files[0].torrent_path if len(candidate.files) == 1 else None)
    links: list[tuple[str, str]] = []
    for f in candidate.files:
        if f.media_file is None:
            continue  # extra senza file locale: lo scarica il client
        if f.media_file.disk_id != disk.id:
            raise ExecutionError(f"'{f.media_file.relative_path}' is on another disk: a hardlink cannot cross disks")
        source_path = _source_path(disk, f.media_file.relative_path)
        try:
            target_path = resolve_scoped(target_root, placement.rel_path(f.torrent_path))
        except ScopeViolation as exc:
            raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc
        if _check_link(source_path, target_path, target_root):
            continue  # già lì, stesso inode: niente da creare (e niente da togliere se fallisce)
        links.append((source_path, target_path))

    if not candidate.download_link:
        raise ExecutionError("Candidate has no download_link: cannot add the torrent to the client")

    seed_job = SeedJob(
        candidate_id=candidate.id, source_media_file_id=anchor.id, final_status="in_progress",
        torrent_client_id=torrent_client_id, expected_missing_bytes=_missing_bytes_for(candidate),
    )
    session.add(seed_job)
    session.commit()

    created: list[str] = []
    add_sent = False
    try:
        created = hardlinks.create_links(links)  # se uno fallisce, toglie quelli appena creati
        seed_job.hardlink_created_at = datetime.now(UTC)
        session.commit()
        logger.info("Creati %d hardlink per candidate %s", len(created), candidate.id)

        save_root = resolve_scoped(target_root, placement.save_dir) if placement.save_dir else target_root
        client_save_path = client_visible_path(session, disk, torrent_client_id, save_root)
        labels = _labels(session, torrent_client_id, candidate)
        add_sent = True
        info_hash = _add_to_client(adapter, candidate, client_save_path, seed_job, skip_recheck, labels,
                                   placement.layout)
        seed_job.info_hash = info_hash
        seed_job.torrent_added_at = datetime.now(UTC)
        seed_job.recheck_status = "pending"
        session.commit()
        logger.info("Torrent aggiunto al client (info_hash=%s), recheck in corso", info_hash)
    except Exception as exc:
        known = _adopt_after_add_error(session, adapter, candidate, seed_job, exc) if add_sent else "absent"
        if known == "adopted":
            return seed_job
        # Solo gli hardlink appena creati da QUESTA esecuzione (i file
        # sorgente in libreria non vengono mai toccati), e solo se il
        # client non ha il torrent: un timeout può voler dire che lo sta
        # ancora scaricando dal tracker, e senza i file partirebbe in download.
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


def _execute_layout_torrent_to_client(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False,
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
    if not candidate.download_link:
        raise ExecutionError("Candidate has no download_link: cannot add the torrent to the client")
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
        if not os.path.isfile(os.path.join(disk.root_path, f.seed_file.relative_path)):
            raise ExecutionError(f"Local file not found: {f.seed_file.relative_path}")

    try:
        save_path_local = resolve_scoped(disk.root_path, root_rel) if root_rel else disk.root_path
    except ScopeViolation as exc:
        raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc

    seed_job = SeedJob(
        candidate_id=candidate.id, source_seed_file_id=anchor.id, final_status="in_progress",
        torrent_client_id=torrent_client_id, expected_missing_bytes=_missing_bytes_for(candidate),
    )
    session.add(seed_job)
    session.commit()
    add_sent = False
    try:
        client_save_path = client_visible_path(session, disk, torrent_client_id, save_path_local)
        labels = _labels(session, torrent_client_id, candidate)
        add_sent = True
        info_hash = _add_to_client(adapter, candidate, client_save_path, seed_job, skip_recheck, labels)
        seed_job.info_hash = info_hash
        seed_job.torrent_added_at = datetime.now(UTC)
        seed_job.recheck_status = "pending"
        session.commit()
        logger.info("Torrent aggiunto al client (info_hash=%s) per file già presenti, recheck in corso", info_hash)
    except Exception as exc:
        if add_sent and _adopt_after_add_error(session, adapter, candidate, seed_job, exc) == "adopted":
            return seed_job
        seed_job.final_status = "failed"
        seed_job.error_message = _error_text(exc)
        session.commit()
        raise ExecutionError(str(exc)) from exc
    return seed_job


def _execute_media_to_torrent(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False,
) -> SeedJob:
    candidate = review.candidate
    media_file = review.media_file
    if media_file is None:
        raise ExecutionError(f"MatchReview {review.id} (media_to_torrent) has no linked media_file")
    disk = media_file.disk

    if not disk.seeding_folders:
        raise ExecutionError(f"Disk '{disk.label}' has no seeding folder configured")

    target_rel_path = disk.effective_new_torrent_rel_path
    try:
        target_root = resolve_scoped(disk.root_path, target_rel_path)
    except ScopeViolation as exc:
        raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc
    if not os.path.isdir(target_root):
        raise ExecutionError(f"Destination folder for new hardlinks not found: {target_root}")

    source_path = _source_path(disk, media_file.relative_path)

    file_list = json.loads(candidate.file_list_json) if candidate.file_list_json else []
    expected_filename = file_list[0] if file_list else os.path.basename(source_path)
    # Un torrent a file singolo può comunque avere una cartella contenitore
    # (candidate.folder) — molte release la usano anche per i film.
    placement = _placement(adapter, candidate, expected_filename)
    try:
        target_path = resolve_scoped(target_root, placement.rel_path(expected_filename))
        save_root = resolve_scoped(target_root, placement.save_dir) if placement.save_dir else target_root
    except ScopeViolation as exc:
        raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc

    reuse = _check_link(source_path, target_path, target_root)

    seed_job = SeedJob(
        candidate_id=candidate.id, source_media_file_id=media_file.id, final_status="in_progress",
        torrent_client_id=torrent_client_id,
    )
    session.add(seed_job)
    session.commit()

    return _create_hardlink_then_seed(
        session, seed_job, candidate, adapter, source_path, target_path, disk, save_root, torrent_client_id,
        skip_recheck, reuse=reuse, layout=placement.layout,
    )


def _create_hardlink_then_seed(
    session: Session,
    seed_job: SeedJob,
    candidate,
    adapter: TorrentClientAdapter,
    source_path: str,
    target_path: str,
    disk: Disk,
    target_root: str,
    torrent_client_id: int | None = None,
    skip_recheck: bool = False,
    reuse: bool = False,
    layout: str = "Original",
) -> SeedJob:
    if not candidate.download_link:
        seed_job.final_status = "failed"
        seed_job.error_message = "Candidate has no download_link: cannot add the torrent to the client"
        session.commit()
        raise ExecutionError(seed_job.error_message)

    add_sent = False
    try:
        if not reuse:  # già lì con lo stesso inode (_check_link): un cross-seed
            hardlinks.create_links([(source_path, target_path)])
        seed_job.hardlink_created_at = datetime.now(UTC)
        session.commit()
        logger.info("Hardlink %s per candidate %s: %s", "riusato" if reuse else "creato", candidate.id, target_path)

        client_save_path = client_visible_path(session, disk, torrent_client_id, target_root)
        labels = _labels(session, torrent_client_id, candidate)
        add_sent = True
        info_hash = _add_to_client(adapter, candidate, client_save_path, seed_job, skip_recheck, labels, layout)
        seed_job.info_hash = info_hash
        seed_job.torrent_added_at = datetime.now(UTC)
        seed_job.recheck_status = "pending"
        session.commit()
        logger.info("Torrent aggiunto al client (info_hash=%s), recheck in corso", info_hash)
    except Exception as exc:
        if add_sent and _adopt_after_add_error(session, adapter, candidate, seed_job, exc) == "adopted":
            return seed_job
        seed_job.final_status = "failed"
        seed_job.error_message = _error_text(exc)
        session.commit()
        raise ExecutionError(str(exc)) from exc

    return seed_job


def _execute_torrent_to_client(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False,
) -> SeedJob:
    """Il file è già presente sul filesystem (docs/SPEC.md sezione 3): mai
    un nuovo hardlink, solo l'aggiunta al client puntando alla cartella che
    già lo contiene."""
    candidate = review.candidate
    seed_file = review.seed_file
    if seed_file is None:
        raise ExecutionError(f"MatchReview {review.id} (torrent_to_client) has no linked seed_file")
    disk = seed_file.disk

    if not candidate.download_link:
        raise ExecutionError("Candidate has no download_link: cannot add the torrent to the client")

    source_path = os.path.join(disk.root_path, seed_file.relative_path)
    if not os.path.isfile(source_path):
        raise ExecutionError(f"Local file not found: {source_path}")

    seed_job = SeedJob(
        candidate_id=candidate.id, source_seed_file_id=seed_file.id, final_status="in_progress",
        torrent_client_id=torrent_client_id,
    )
    session.add(seed_job)
    session.commit()

    save_path_local = os.path.dirname(source_path)
    add_sent = False
    try:
        client_save_path = client_visible_path(session, disk, torrent_client_id, save_path_local)
        labels = _labels(session, torrent_client_id, candidate)
        add_sent = True
        info_hash = _add_to_client(adapter, candidate, client_save_path, seed_job, skip_recheck, labels)
        seed_job.info_hash = info_hash
        seed_job.torrent_added_at = datetime.now(UTC)
        seed_job.recheck_status = "pending"
        session.commit()
        logger.info(
            "Torrent aggiunto al client (info_hash=%s) per file già presente, recheck in corso", info_hash
        )
    except Exception as exc:
        if add_sent and _adopt_after_add_error(session, adapter, candidate, seed_job, exc) == "adopted":
            return seed_job
        seed_job.final_status = "failed"
        seed_job.error_message = _error_text(exc)
        session.commit()
        raise ExecutionError(str(exc)) from exc

    return seed_job


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
        seed_job.error_message = f"Recheck failed, client state: {status.state}"
        logger.warning("Recheck fallito per seed_job %s: stato client %s", seed_job.id, status.state)
    session.commit()
    return seed_job


def retry_seed_job(
    session: Session, seed_job: SeedJob, adapter: TorrentClientAdapter, torrent_client_id: int | None = None
) -> SeedJob:
    """Ritenta un seed_job failed. Se ha già un info_hash, il problema era
    probabilmente solo il recheck mai confermato: si reinterroga il client
    invece di ripartire da zero (che per torrent_to_client sarebbe comunque
    un no-op, e per media_to_torrent fallirebbe su "il path esiste già")."""
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
