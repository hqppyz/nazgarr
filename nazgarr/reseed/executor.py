"""Esecutore: hardlink + aggiunta al client (direzione media_to_torrent)
o solo aggiunta al client (direzione torrent_to_client, il file esiste
già) — sempre con recheck forzato, mai skip_checking (docs/SPEC.md
sezione 8). Ordine dei passi per media_to_torrent, mai bypassabile:
1. verifica st_dev sorgente/destinazione (mai un cross-device silente)
2. hardlink col nome esatto atteso dal tracker
3. add_torrent sul client, sempre con force_recheck=True, fermo: parte solo
   a recheck riuscito (reconcile_seed_job, decisione dell'utente 2026-10-18)

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
    TorrentStatus,
    is_stopped_state,
    layout_kwargs,
    stopped_kwargs,
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
from nazgarr.reseed.placement import Placement, placement_for
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


def _structure_from_torrent(session: Session, candidate: Candidate, fetch_torrent: FetchTorrent | None) -> FetchTorrent:
    """Un candidato il cui .torrent il matching non ha mai letto (niente
    piece_length, che c'è solo per una struttura letta da un .torrent: il
    download era fallito): la cartella e i nomi dei file vengono solo dal
    catalogo del tracker, cioè da chi ha caricato il torrent. Anche dopo un
    controllo completo passato, che impara l'info hash e corregge la cartella
    ma ritrova i file anche per nome: prima bastava l'info hash per saltare
    questo controllo (audit 2026-10-18). Prima di decidere dove vanno
    gli hardlink, la struttura vera dal .torrent: la cartella si corregge (il
    catalogo UNIT3D spesso non la riporta), e i file devono essere gli
    stessi, altrimenti niente (audit 2026-10-18: un nome del catalogo poteva
    mettere l'hardlink nella cartella di un altro torrent). Restituisce i
    byte già scaricati, per non riscaricarli."""
    content = (fetch_torrent or _download_torrent)(candidate)
    try:
        parsed = parse_torrent_info(content)
    except TorrentMetainfoError as exc:
        raise ExecutionError(f"The tracker sent an invalid .torrent: {exc}") from exc
    if sorted(f.torrent_path for f in candidate.files) != sorted(e.path for e in parsed.files):
        raise ExecutionError(
            "The files of the torrent are not the ones the tracker's catalogue listed: nothing created. "
            "Search it again (Search now) to read its real structure"
        )
    folder = parsed.name if parsed.is_multi_file else None
    if candidate.folder != folder:
        logger.info("Candidate %s: cartella del torrent %r invece di %r (dal .torrent)",
                    candidate.id, folder, candidate.folder)
        candidate.folder = folder
        session.commit()
    return lambda _candidate: content


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
    layout: sempre esplicito (Placement), "Original" per file già al loro
    posto: la preferenza del client non li deve spostare.

    Con il recheck del client il torrent entra fermo (decisione dell'utente,
    2026-10-18; stopped_kwargs, ogni adapter incluso) e parte solo quando il
    recheck è riuscito (reconcile_seed_job): avviato, con un recheck fallito
    scaricava i piece mancanti dentro gli hardlink, cioè nei file della
    libreria, fino al reconcile che lo fermava (minuti, o una run intera).
    Senza recheck (verificato al 100% da Nazgarr) parte subito, come prima.

    Il .torrent va come file locale temporaneo, che ogni adapter manda al
    client col suo contenuto (docs/SDK.md): mai il link del tracker."""
    skip_recheck = skip_recheck and getattr(adapter, "can_skip_recheck", True)
    extra = {"skip_check_verified": True} if skip_recheck else stopped_kwargs(adapter)
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


def _client_layout(adapter: TorrentClientAdapter) -> str:
    try:
        layout = adapter.content_layout()
    except AttributeError:
        return "Original"  # un adapter senza content_layout segue il .torrent
    except Exception:
        logger.warning("Layout del contenuto del client non letto: uso Original", exc_info=True)
        return "Original"
    return layout if layout in CONTENT_LAYOUTS else "Original"


def _placement(adapter: TorrentClientAdapter, candidate, single_file_name: str | None) -> Placement:
    """Dove vanno i nuovi hardlink perché il torrent li trovi rispettando il
    layout del contenuto scelto dall'utente nel client: la regola è in
    nazgarr/reseed/placement.py, la stessa con cui seed_refresh e il
    controllo completo li cercano dopo."""
    return placement_for(_client_layout(adapter), candidate.folder, single_file_name)


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


def _check_link(source_path: str, target_path: str, target_root: str) -> str | None:
    """I controlli comuni (nazgarr/library/hardlinks.py::check_link) prima di creare
    un hardlink, sulla destinazione così come è scritta (target_root più il
    percorso del torrent, mai già risolta): risolta, un link simbolico al
    suo posto non si vedeva più, e l'hardlink nasceva dove puntava (audit
    2026-10-18). Restituisce la destinazione risolta da passare a
    create_links, o None se è già lo stesso file (stesso inode): un
    cross-seed della stessa release con lo stesso nome su un altro tracker
    riusa quell'hardlink. Un altro file al suo posto, o un link simbolico,
    resta un errore: mai sovrascritto né seguito."""
    try:
        return hardlinks.check_link(source_path, target_path, target_root)
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
        # Lo stesso testo inglese salvato sul seed_job, senza chiavi: prima
        # str(exc) di un errore con codice era il codice nudo (es.
        # "client_cannot_see_path"), e quello di un client il suo messaggio
        # così com'era (audit 2026-10-18).
        raise ExecutionError(safe_error(seed_job.error_message)) from exc
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
    if candidate.piece_length is None:
        _require_download_link(candidate)
        fetch_torrent = _structure_from_torrent(session, candidate, fetch_torrent)

    placement = _placement(adapter, candidate, candidate.files[0].torrent_path if len(candidate.files) == 1 else None)
    links: list[tuple[str, str]] = []
    for f in candidate.files:
        if f.media_file is None:
            continue  # extra senza file locale: lo scarica il client
        if f.media_file.disk_id != disk.id:
            raise ExecutionError(f"'{f.media_file.relative_path}' is on another disk: a hardlink cannot cross disks")
        source_path = _source_path(disk, f.media_file.relative_path)
        target_path = _check_link(source_path, os.path.join(target_root, placement.rel_path(f.torrent_path)),
                                  target_root)
        if target_path is None:
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
    if candidate.piece_length is None:
        fetch_torrent = _structure_from_torrent(session, candidate, fetch_torrent)

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
    # None: già lì, stesso inode (un cross-seed).
    target_path = _check_link(source_path, os.path.join(target_root, placement.rel_path(expected_filename)),
                              target_root)
    save_root = _in_scope(target_root, placement.save_dir) if placement.save_dir else target_root
    _require_download_link(candidate)

    seed_job = _new_seed_job(session, candidate, torrent_client_id, source_media_file_id=media_file.id)
    return _seed(session, seed_job, review, adapter, torrent_client_id, disk, save_root, skip_recheck,
                 fetch_torrent, links=[] if target_path is None else [(source_path, target_path)],
                 layout=placement.layout)


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
    raggiunge uno stato definitivo (mai un'attesa bloccante qui dentro).

    Un reseed entra fermo (_add_to_client): qui parte, con start(), solo a
    recheck riuscito (al 100%, o con i soli extra che si sapeva mancanti);
    con il recheck fallito resta fermo, e il seed job fallito lo dice."""
    if seed_job.info_hash is None:
        raise ExecutionError(f"SeedJob {seed_job.id} does not have an info_hash yet")
    return _reconcile_with(session, seed_job, adapter, adapter.get_torrent_status(seed_job.info_hash))


def _recheck_outcome(seed_job: SeedJob, status: TorrentStatus) -> str:
    """L'esito del recheck di un seed job: quello del client, salvo un
    recheck finito a cui mancano solo i file extra che si sapeva di non
    avere (nfo, sottotitoli, sample, expected_missing_bytes), che è "ok":
    il client li scarica dopo l'avvio."""
    allowed = seed_job.expected_missing_bytes or 0
    if (
        status.recheck_status == "failed" and status.incomplete and allowed > 0
        and status.amount_left is not None and status.amount_left <= allowed
    ):
        logger.info(
            "Seed_job %s: recheck ok, il client scarica %d byte di file extra mancanti",
            seed_job.id, status.amount_left,
        )
        return "ok"
    return status.recheck_status


def _reconcile_with(session: Session, seed_job: SeedJob, adapter: TorrentClientAdapter,
                    status: TorrentStatus) -> SeedJob:
    recheck_status = _recheck_outcome(seed_job, status)
    seed_job.recheck_status = recheck_status
    if recheck_status == "ok":
        seed_job.error_message = None  # un retry riuscito: il fallimento di prima non vale più
        if is_stopped_state(status.state) and not _start_after_recheck(adapter, seed_job):
            session.commit()
            return seed_job  # resta in corso: il prossimo reconcile riprova ad avviarlo
        seed_job.final_status = "seeding"
        logger.info("Recheck ok, seed_job %s in seeding (info_hash=%s)", seed_job.id, seed_job.info_hash)
    elif recheck_status == "failed":
        seed_job.final_status = "failed"
        seed_job.error_message = f"Recheck failed, client state: {status.state}" + _stop_after_failed_recheck(
            adapter, seed_job, status.state)
        logger.warning("Recheck fallito per seed_job %s: stato client %s", seed_job.id, status.state)
    session.commit()
    return seed_job


STARTED_LATE = ("The recheck passed, but the client did not start the torrent: Nazgarr tries again at the "
                "next check, or start it in the client")
CANNOT_START = "The recheck passed, but this client cannot be told to start it: start it in the client"


def _start_after_recheck(adapter: TorrentClientAdapter, seed_job: SeedJob) -> bool:
    """Avvia un torrent fermo dopo un recheck riuscito: un reseed, che entra
    sempre fermo (decisione dell'utente, 2026-10-18), o la condizione di
    arresto "file controllati" di un client. False se il client non l'ha
    avviato: il seed job resta in corso, col perché, e il reconcile dopo
    riprova (prima diventava "seeding" con il torrent fermo per sempre).
    Un adapter che start() non ce l'ha (un plugin senza la classe base) o
    non lo implementa non lo farà mai: "seeding", col messaggio di avviarlo
    nel client, invece di riprovare per sempre a ogni reconcile."""
    start = getattr(adapter, "start", None)
    try:
        if not callable(start):
            raise NotImplementedError
        start(seed_job.info_hash)
    except NotImplementedError:
        logger.warning("Seed_job %s: recheck riuscito, il client non sa avviare %s", seed_job.id,
                       seed_job.info_hash)
        seed_job.error_message = CANNOT_START
        return True
    except Exception as exc:
        logger.warning("Seed_job %s: recheck riuscito, avvio fallito", seed_job.id, exc_info=True)
        seed_job.error_message = f"{STARTED_LATE} ({safe_error(exc)})"
        return False
    logger.info("Seed_job %s: recheck riuscito, torrent avviato", seed_job.id)
    return True


def _stop_after_failed_recheck(adapter: TorrentClientAdapter, seed_job: SeedJob, state: str | None) -> str:
    """Un reseed col recheck fallito resta fermo nel client: entra fermo
    (decisione dell'utente, 2026-10-18), e uno che non lo è (aggiunto da un
    plugin senza can_add_stopped, o avviato a mano durante il recheck) si
    ferma (audit 2026-10-18). Avviato, scaricherebbe i piece che mancano
    scrivendoli nei file a save_path, che sono hardlink dei file in libreria
    (gli stessi byte), o i file già nella cartella dei torrent. Niente di
    approvato dall'utente. Ritorna la coda del messaggio del seed job. Un
    retry lo fa ricontrollare (adopt_for_retry), e il reconcile dopo lo
    avvia se il recheck riesce (_start_after_recheck)."""
    if is_stopped_state(state):
        return ("; left stopped in the client, so it downloads nothing into the linked files: recheck it in the "
                "client, or Retry once the files are right")
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


def adopt_for_retry(session: Session, seed_job: SeedJob, adapter: TorrentClientAdapter) -> SeedJob | None:
    """La parte di un retry che segue un torrent già nel client, senza
    creare niente: con un info_hash si reinterroga il client; senza, se il
    client ha comunque il torrent del candidato (l'aggiunta fallita può
    essere arrivata lo stesso), lo si segue. None = va rifatto da zero.

    Con un info_hash e il torrent fermo col recheck fallito (un reseed entra
    fermo e ci resta, decisione dell'utente del 2026-10-18) si chiede un
    nuovo recheck: un torrent fermo il client non lo ricontrolla da solo, e
    rileggerlo diceva di nuovo "failed" anche coi file ora giusti. Il retry
    è l'approvazione dell'utente, ed è un controllo, mai un avvio: il seed
    job torna in corso e il reconcile dopo lo avvia solo se riesce."""
    if seed_job.info_hash:
        logger.info("Retry seed_job %s: info_hash già presente, reinterrogo il client", seed_job.id)
        status = adapter.get_torrent_status(seed_job.info_hash)
        if _recheck_outcome(seed_job, status) == "failed" and is_stopped_state(status.state) and _recheck_for_retry(
                adapter, seed_job):
            seed_job.final_status, seed_job.recheck_status, seed_job.error_message = "in_progress", "pending", None
            session.commit()
            return seed_job
        seed_job.final_status = "in_progress"
        session.commit()
        return _reconcile_with(session, seed_job, adapter, status)
    candidate = session.get(Candidate, seed_job.candidate_id)
    if candidate is not None and candidate.info_hash:
        try:
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
    return None


def _recheck_for_retry(adapter: TorrentClientAdapter, seed_job: SeedJob) -> bool:
    """Il recheck chiesto da un retry. False se l'adapter non lo sa fare (un
    plugin senza recheck): il retry rilegge soltanto, come prima. Un errore
    del client è un retry fallito, e il seed job resta com'era."""
    recheck = getattr(adapter, "recheck", None)
    try:
        if not callable(recheck):
            raise NotImplementedError
        recheck(seed_job.info_hash)
    except NotImplementedError:
        logger.warning("Retry seed_job %s: il client non sa ricontrollare %s", seed_job.id, seed_job.info_hash)
        return False
    except Exception as exc:
        raise ExecutionError(f"The client did not take the recheck ({safe_error(exc)}): try again, or recheck "
                             "it in the client") from exc
    logger.info("Retry seed_job %s: recheck chiesto al client, resta fermo fino all'esito", seed_job.id)
    return True


def review_of(session: Session, seed_job: SeedJob) -> MatchReview:
    """La review che ha lanciato l'esecuzione."""
    return (
        session.query(MatchReview)
        .filter(MatchReview.candidate_id == seed_job.candidate_id)
        .filter(
            (MatchReview.media_file_id == seed_job.source_media_file_id)
            if seed_job.source_media_file_id is not None
            else (MatchReview.seed_file_id == seed_job.source_seed_file_id)
        )
        .one()
    )


def retry_from_scratch(
    session: Session, seed_job: SeedJob, adapter: TorrentClientAdapter, torrent_client_id: int | None = None,
    skip_recheck: bool = False,
) -> SeedJob:
    """Una nuova esecuzione della stessa review: gli hardlink già al loro
    posto con lo stesso inode si riusano, e il .torrent si riscarica e si
    ricontrolla contro l'info hash del candidato."""
    logger.info("Retry seed_job %s: riparto da zero (nessun info_hash mai ottenuto)", seed_job.id)
    return execute_review(session, review_of(session, seed_job), adapter, torrent_client_id, skip_recheck=skip_recheck)

