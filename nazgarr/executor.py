"""Esecutore: hardlink + aggiunta al client (direzione media_to_torrent)
o solo aggiunta al client (direzione torrent_to_client, il file esiste
già) — sempre con recheck forzato, mai skip_checking (docs/SPEC.md
sezione 8). Ordine dei passi per media_to_torrent, mai bypassabile:
1. verifica st_dev sorgente/destinazione (mai un cross-device silente)
2. hardlink col nome esatto atteso dal tracker
3. add_torrent sul client, sempre con force_recheck=True

Un candidato con righe candidate_file (nazgarr/torrent_layout.py: film con
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
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from nazgarr import client_labels, client_paths, settings_repo
from nazgarr.adapters.torrent_client.base import TorrentClientAdapter
from nazgarr.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.models import Disk, DiskTorrentClient, MatchReview, SeedJob, TorrentClient
from nazgarr.tmdb_client import TMDBClient
from nazgarr.torrent_layout import expected_missing_bytes

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Errore esplicito che impedisce l'esecuzione — mai un fallimento silente."""


def client_visible_path(session: Session, disk: Disk, torrent_client_id: int | None, local_path: str) -> str:
    """Traduce un path lato Nazgarr nel path equivalente visto DA QUESTO
    client torrent, quando i due girano in container/mount diversi per lo
    stesso disco fisico (disk_torrent_client: torrent_client_root_path e
    local_rel_path per la coppia (disk, torrent_client_id), nazgarr/client_paths.py).
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


def _check_same_filesystem(source_path: str, torrents_root: str) -> None:
    source_dev = os.stat(source_path).st_dev
    target_dev = os.stat(torrents_root).st_dev
    if source_dev != target_dev:
        raise ExecutionError(
            f"Source and destination are on different devices ({source_dev} != {target_dev}): "
            "a hardlink cannot cross filesystems, see docs/SPEC.md section 4"
        )


def execute_review(
    session: Session, review: MatchReview, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False,
) -> SeedJob:
    """skip_recheck: SOLO dopo un controllo completo di Nazgarr al 100% senza
    extra mancanti, con l'opzione accesa dall'utente (nazgarr/review.py). In ogni
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
    (nazgarr/client_labels.py). TMDB, per sapere se è un anime, solo se il
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
    labels: dict | None = None,
) -> str:
    """Aggiunge il torrent al client. Il recheck del client si salta solo se
    il chiamante l'ha verificato lui stesso al 100% (skip_recheck): resta
    scritto sul seed_job, così si vede quali esecuzioni sono passate così.
    labels: categoria e tag del client (_labels), solo se ce ne sono.
    Un client che non sa saltarlo (can_skip_recheck) lo fa comunque."""
    skip_recheck = skip_recheck and getattr(adapter, "can_skip_recheck", True)
    extra = {"skip_check_verified": True} if skip_recheck else {}
    info_hash = adapter.add_torrent(
        candidate.download_link, save_path=save_path, force_recheck=True,
        expected_info_hash=candidate.info_hash, **extra, **(labels or {}),
    )
    seed_job.recheck_skipped = skip_recheck or None
    return info_hash


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


def _reusable_link(source_path: str, target_path: str) -> bool:
    """True se la destinazione esiste già ed è lo stesso file della sorgente
    (stesso inode, mai un link simbolico): un cross-seed della stessa release
    con lo stesso nome su un altro tracker riusa quell'hardlink, gli stessi
    byte. Un altro file al suo posto resta un errore: mai sovrascritto."""
    if not os.path.lexists(target_path):
        return False
    if not os.path.islink(target_path) and os.path.isfile(target_path) and os.path.samefile(source_path, target_path):
        return True
    raise ExecutionError(f"Destination path already exists: {target_path}")


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

    links: list[tuple[str, str]] = []
    for f in candidate.files:
        if f.media_file is None:
            continue  # extra senza file locale: lo scarica il client
        if f.media_file.disk_id != disk.id:
            raise ExecutionError(f"'{f.media_file.relative_path}' is on another disk: a hardlink cannot cross disks")
        source_path = os.path.join(disk.root_path, f.media_file.relative_path)
        if not os.path.isfile(source_path):
            raise ExecutionError(f"Local file not found: {source_path}")
        try:
            target_path = resolve_scoped(target_root, _torrent_rel_path(candidate, f.torrent_path))
        except ScopeViolation as exc:
            raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc
        _check_same_filesystem(source_path, target_root)
        if _reusable_link(source_path, target_path):
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
    try:
        for source_path, target_path in links:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            os.link(source_path, target_path)
            created.append(target_path)
        seed_job.hardlink_created_at = datetime.now(UTC)
        session.commit()
        logger.info("Creati %d hardlink per candidate %s", len(created), candidate.id)

        client_save_path = client_visible_path(session, disk, torrent_client_id, target_root)
        info_hash = _add_to_client(adapter, candidate, client_save_path, seed_job, skip_recheck,
                                   _labels(session, torrent_client_id, candidate))
        seed_job.info_hash = info_hash
        seed_job.torrent_added_at = datetime.now(UTC)
        seed_job.recheck_status = "pending"
        session.commit()
        logger.info("Torrent aggiunto al client (info_hash=%s), recheck in corso", info_hash)
    except Exception as exc:
        # Solo gli hardlink appena creati da QUESTA esecuzione: i file
        # sorgente in libreria non vengono mai toccati.
        if seed_job.info_hash is None:
            for path in created:
                try:
                    os.unlink(path)
                except OSError:
                    logger.warning("Impossibile rimuovere l'hardlink %s dopo il fallimento", path)
        seed_job.final_status = "failed"
        seed_job.error_message = str(exc)
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
    try:
        client_save_path = client_visible_path(session, disk, torrent_client_id, save_path_local)
        info_hash = _add_to_client(adapter, candidate, client_save_path, seed_job, skip_recheck,
                                   _labels(session, torrent_client_id, candidate))
        seed_job.info_hash = info_hash
        seed_job.torrent_added_at = datetime.now(UTC)
        seed_job.recheck_status = "pending"
        session.commit()
        logger.info("Torrent aggiunto al client (info_hash=%s) per file già presenti, recheck in corso", info_hash)
    except Exception as exc:
        seed_job.final_status = "failed"
        seed_job.error_message = str(exc)
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

    source_path = os.path.join(disk.root_path, media_file.relative_path)
    if not os.path.isfile(source_path):
        raise ExecutionError(f"Local file not found: {source_path}")

    file_list = json.loads(candidate.file_list_json) if candidate.file_list_json else []
    expected_filename = file_list[0] if file_list else os.path.basename(source_path)
    # Un torrent a file singolo può comunque avere una cartella contenitore
    # (candidate.folder) — molte release la usano anche per i film.
    relative_target = os.path.join(candidate.folder, expected_filename) if candidate.folder else expected_filename
    try:
        target_path = resolve_scoped(target_root, relative_target)
    except ScopeViolation as exc:
        raise ExecutionError(f"Path outside the allowed scope: {exc.candidate}") from exc

    _check_same_filesystem(source_path, target_root)
    reuse = _reusable_link(source_path, target_path)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    seed_job = SeedJob(
        candidate_id=candidate.id, source_media_file_id=media_file.id, final_status="in_progress",
        torrent_client_id=torrent_client_id,
    )
    session.add(seed_job)
    session.commit()

    return _create_hardlink_then_seed(
        session, seed_job, candidate, adapter, source_path, target_path, disk, target_root, torrent_client_id,
        skip_recheck, reuse=reuse,
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
) -> SeedJob:
    if not candidate.download_link:
        seed_job.final_status = "failed"
        seed_job.error_message = "Candidate has no download_link: cannot add the torrent to the client"
        session.commit()
        raise ExecutionError(seed_job.error_message)

    try:
        if not reuse:  # già lì con lo stesso inode (_reusable_link): un cross-seed
            os.link(source_path, target_path)
        seed_job.hardlink_created_at = datetime.now(UTC)
        session.commit()
        logger.info("Hardlink %s per candidate %s: %s", "riusato" if reuse else "creato", candidate.id, target_path)

        client_save_path = client_visible_path(session, disk, torrent_client_id, target_root)
        info_hash = _add_to_client(adapter, candidate, client_save_path, seed_job, skip_recheck,
                                   _labels(session, torrent_client_id, candidate))
        seed_job.info_hash = info_hash
        seed_job.torrent_added_at = datetime.now(UTC)
        seed_job.recheck_status = "pending"
        session.commit()
        logger.info("Torrent aggiunto al client (info_hash=%s), recheck in corso", info_hash)
    except Exception as exc:
        seed_job.final_status = "failed"
        seed_job.error_message = str(exc)
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
    try:
        client_save_path = client_visible_path(session, disk, torrent_client_id, save_path_local)
        info_hash = _add_to_client(adapter, candidate, client_save_path, seed_job, skip_recheck,
                                   _labels(session, torrent_client_id, candidate))
        seed_job.info_hash = info_hash
        seed_job.torrent_added_at = datetime.now(UTC)
        seed_job.recheck_status = "pending"
        session.commit()
        logger.info(
            "Torrent aggiunto al client (info_hash=%s) per file già presente, recheck in corso", info_hash
        )
    except Exception as exc:
        seed_job.final_status = "failed"
        seed_job.error_message = str(exc)
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
