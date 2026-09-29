"""Controllo completo dei piece hash (100%) fra i file locali e il .torrent
di un candidato: la stessa prova del recheck del client, fatta qui per
capire perché un torrent non torna in seed.

Il matching verifica solo un campione di piece (torrent_layout.PIECE_SAMPLE_SIZE):
basta a scartare release diverse, ma non dice quale piece il client rifiuta.
Qui si legge ogni piece del torrent, compresi quelli a cavallo fra due file
(concatenando i file locali nell'ordine del torrent, come fa il client), e
per ogni file si conta quanti piece coincidono, quanti no e quanti non si
possono leggere perché il file manca.

Dove si leggono i file: prima dove li vede il client (gli hardlink creati
dall'esecuzione, o il file lato torrent), poi il file in libreria abbinato.
Così un risultato al 100% sul file in libreria ma con file "mancanti" nella
posizione del seed dice che il problema è il percorso, non i dati.

Sola lettura: nessun file, nessun client e nessuna review viene toccato.
Gira in background (può leggere decine di GB), uno alla volta, con lo stato
in memoria del processo web: è una diagnosi, non un dato da conservare.
"""

import hashlib
import logging
import os
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app import adapter_factory
from app.file_types import is_video
from app.models import Candidate, MatchReview, MediaFile, SeedFile, SeedJob
from app.torrent_file import TorrentFileEntry, TorrentInfo, compute_info_hash, parse_torrent_info

logger = logging.getLogger(__name__)

MAX_BAD_PIECES_LISTED = 20
MAX_KEPT_CHECKS = 20


class FullCheckError(Exception):
    pass


class CheckCancelled(Exception):
    pass


@dataclass
class FileCheck:
    torrent_path: str
    size_bytes: int
    local_path: str | None  # percorso assoluto letto, None = nessun file locale trovato
    location: str | None  # "seed" (dove lo vede il client) | "library" | None
    local_size_bytes: int | None
    pieces: int = 0
    ok: int = 0
    mismatched: int = 0
    unreadable: int = 0  # piece che toccano un file mancante o più corto del dovuto
    first_bad_offset: int | None = None  # byte dall'inizio del file del primo piece non valido


@dataclass
class CheckResult:
    torrent_name: str
    info_hash: str
    expected_info_hash: str | None
    piece_length: int
    pieces: int
    ok: int
    mismatched: int
    unreadable: int
    bad_pieces: list[int]
    files: list[FileCheck]

    @property
    def percent(self) -> float:
        return 100.0 * self.ok / self.pieces if self.pieces else 0.0


Locator = Callable[[TorrentFileEntry], tuple[str | None, str | None]]


def _file_size(path: str | None) -> int | None:
    try:
        return os.path.getsize(path) if path else None
    except OSError:
        return None


def verify_all_pieces(
    parsed: TorrentInfo,
    locate: Locator,
    on_progress: Callable[[int], None] = lambda _: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[list[FileCheck], list[int]]:
    """Ogni piece del torrent contro i file locali concatenati nell'ordine
    del torrent. Un piece che tocca un file mancante (o più corto) è
    "unreadable" per ogni file che tocca, mai un mismatch: dire "i dati sono
    diversi" quando il file semplicemente non c'è porterebbe fuori strada."""
    checks: list[FileCheck] = []
    for entry in parsed.files:
        local_path, location = locate(entry)
        checks.append(FileCheck(
            torrent_path=entry.path, size_bytes=entry.length, local_path=local_path, location=location,
            local_size_bytes=_file_size(local_path),
        ))

    handles: dict[int, object] = {}
    bad: list[int] = []
    first = 0  # primo file che può ancora toccare il piece corrente
    try:
        for idx, expected in enumerate(parsed.pieces):
            if cancelled():
                raise CheckCancelled()
            start = idx * parsed.piece_length
            end = min(start + parsed.piece_length, parsed.total_length)
            while first < len(parsed.files) and parsed.files[first].offset + parsed.files[first].length <= start:
                handle = handles.pop(first, None)
                if handle is not None:
                    handle.close()
                first += 1
            touched: list[int] = []
            digest = hashlib.sha1()
            readable = True
            i = first
            while i < len(parsed.files) and parsed.files[i].offset < end:
                entry = parsed.files[i]
                if entry.length > 0:
                    touched.append(i)
                    lo = max(start, entry.offset) - entry.offset
                    hi = min(end, entry.offset + entry.length) - entry.offset
                    data = _read(handles, i, checks[i].local_path, lo, hi - lo) if readable else None
                    if data is None or len(data) != hi - lo:
                        readable = False
                    else:
                        digest.update(data)
                i += 1
            if readable:
                good = digest.digest() == expected
            for i in touched:
                check = checks[i]
                check.pieces += 1
                if not readable:
                    check.unreadable += 1
                elif good:
                    check.ok += 1
                else:
                    check.mismatched += 1
                if (not readable or not good) and check.first_bad_offset is None:
                    check.first_bad_offset = max(start - parsed.files[i].offset, 0)
            if not readable or not good:
                bad.append(idx)
            on_progress(end)
    finally:
        for handle in handles.values():
            handle.close()
    return checks, bad


def _read(handles: dict, index: int, path: str | None, offset: int, length: int) -> bytes | None:
    if path is None:
        return None
    try:
        handle = handles.get(index)
        if handle is None:
            handle = handles[index] = open(path, "rb")  # noqa: SIM115 — chiuso da verify_all_pieces
        handle.seek(offset)
        return handle.read(length)
    except OSError:
        return None


def _abs(disk, relative_path: str) -> str:
    return os.path.normpath(os.path.join(disk.root_path, relative_path))


def _anchor(session: Session, candidate: Candidate, seed_job: SeedJob | None, media_file_id: int | None):
    """Il file locale di un candidato a file singolo (che non ha
    candidate_file): quello indicato, quello dell'esecuzione o della review,
    in quest'ordine."""
    if media_file_id is not None:
        return session.get(MediaFile, media_file_id)
    if seed_job is not None:
        if seed_job.source_media_file_id is not None:
            return session.get(MediaFile, seed_job.source_media_file_id)
        if seed_job.source_seed_file_id is not None:
            return session.get(SeedFile, seed_job.source_seed_file_id)
    review = session.query(MatchReview).filter_by(candidate_id=candidate.id).order_by(MatchReview.id.desc()).first()
    if review is not None:
        return review.media_file or review.seed_file
    # Candidato solo valutato (nessuna review): l'unico video del contenuto
    # (per le serie media_item è già il singolo episodio).
    videos = [mf for mf in session.query(MediaFile).filter_by(media_item_id=candidate.media_item_id).all()
              if is_video(mf.relative_path)]
    return videos[0] if len(videos) == 1 else None


def build_locator(session: Session, candidate: Candidate, seed_job: SeedJob | None,
                  media_file_id: int | None = None) -> Locator:
    by_path = {f.torrent_path: f for f in candidate.files}
    anchor = None if candidate.files else _anchor(session, candidate, seed_job, media_file_id)
    if not candidate.files and anchor is None:
        raise FullCheckError("No local file is linked to this torrent: open the check from one of its files")

    seed_root = None
    if seed_job is not None and candidate.direction == "media_to_torrent":
        source = session.get(MediaFile, seed_job.source_media_file_id) if seed_job.source_media_file_id else None
        if source is not None:
            base = os.path.join(source.disk.effective_new_torrent_rel_path or "", candidate.folder or "")
            seed_root = _abs(source.disk, base)

    def locate(entry: TorrentFileEntry) -> tuple[str | None, str | None]:
        if seed_root is not None:
            seeded = os.path.normpath(os.path.join(seed_root, entry.path))
            if os.path.isfile(seeded):
                return seeded, "seed"
        matched = by_path.get(entry.path)
        if matched is None and candidate.files:
            base = os.path.basename(entry.path).lower()
            matched = next((f for f in candidate.files if os.path.basename(f.torrent_path).lower() == base), None)
        local = (matched.seed_file or matched.media_file) if matched is not None else anchor
        if local is None:
            return None, None
        location = "seed" if isinstance(local, SeedFile) else "library"
        path = _abs(local.disk, local.relative_path)
        return (path, location) if os.path.isfile(path) else (None, None)

    return locate


def run_full_check(
    session: Session,
    candidate: Candidate,
    seed_job: SeedJob | None = None,
    media_file_id: int | None = None,
    fetch_torrent: Callable[[Candidate], bytes] | None = None,
    on_start: Callable[[int], None] = lambda _: None,
    on_progress: Callable[[int], None] = lambda _: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> CheckResult:
    if fetch_torrent is None:
        fetch_torrent = _download_torrent
    content = fetch_torrent(candidate)
    parsed = parse_torrent_info(content)
    locate = build_locator(session, candidate, seed_job, media_file_id)
    on_start(parsed.total_length)
    files, bad = verify_all_pieces(parsed, locate, on_progress, cancelled)
    # bad_pieces è troncato per la risposta: i totali si contano su tutti.
    bad_set = set(bad)
    unreadable_set = unreadable_pieces(parsed, files)
    unreadable = len(bad_set & unreadable_set)
    mismatched = len(bad_set) - unreadable
    ok = len(parsed.pieces) - len(bad_set)
    return CheckResult(
        torrent_name=parsed.name,
        info_hash=compute_info_hash(content),
        expected_info_hash=(seed_job.info_hash if seed_job is not None else None) or candidate.info_hash,
        piece_length=parsed.piece_length,
        pieces=len(parsed.pieces),
        ok=ok,
        mismatched=mismatched,
        unreadable=unreadable,
        bad_pieces=bad[:MAX_BAD_PIECES_LISTED],
        files=files,
    )


def verdict(result: CheckResult) -> tuple[bool, str | None]:
    """Il torrent passerà il recheck del client? Sì se nessun piece è diverso
    e ogni file ha la sua copia locale della dimensione giusta, tranne gli
    extra che mancano in locale (nfo, sample): quelli li scarica il client
    dopo il recheck, lo stesso margine di seed_job.expected_missing_bytes.
    Un video mancante o di dimensione diversa non passa mai."""
    if result.mismatched:
        return False, f"{result.mismatched} of {result.pieces} pieces differ from the torrent"
    for f in result.files:
        if f.local_path is None:
            if is_video(f.torrent_path):
                return False, f"'{f.torrent_path}' has no local file"
            continue
        if f.local_size_bytes != f.size_bytes:
            return False, (
                f"'{f.torrent_path}' is {f.local_size_bytes} bytes locally, the torrent expects {f.size_bytes}"
            )
    return True, None


def unreadable_pieces(parsed: TorrentInfo, files: list[FileCheck]) -> set[int]:
    """Piece che toccano un file senza copia locale leggibile per intero."""
    result: set[int] = set()
    for entry, check in zip(parsed.files, files, strict=True):
        if entry.length == 0:
            continue
        if check.local_path is None or (check.local_size_bytes or 0) < entry.length:
            first = entry.offset // parsed.piece_length
            last = (entry.offset + entry.length - 1) // parsed.piece_length
            result.update(range(first, last + 1))
    return result


def _download_torrent(candidate: Candidate) -> bytes:
    if not candidate.download_link:
        raise FullCheckError("This candidate has no download link for its .torrent")
    adapter = adapter_factory.build_tracker_adapter(candidate.tracker)
    try:
        return adapter.download_torrent(candidate.download_link)
    except Exception as exc:
        raise FullCheckError(f"Could not download the .torrent from {candidate.tracker.label}: {exc}") from exc


# --- Esecuzione in background -------------------------------------------------


@dataclass
class CheckState:
    id: str
    candidate_id: int
    seed_job_id: int | None
    media_file_id: int | None
    label: str
    status: str = "queued"  # queued | running | done | failed | cancelled
    bytes_total: int | None = None
    bytes_done: int = 0
    error: str | None = None
    result: dict | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    cancel_requested: bool = False
    # "manual" (pulsante Full hash check) | "verify" (prima di eseguire una
    # review approvata, app/review.py::request_approval).
    purpose: str = "manual"
    review_id: int | None = None
    stage: str = "verifying"  # verifying | executing (solo purpose="verify", dopo un controllo superato)
    verdict: str | None = None  # passed | failed
    verdict_reason: str | None = None
    execution: str | None = None  # added | failed | no_client | skipped
    execution_error: str | None = None


_lock = threading.Lock()
_checks: dict[str, CheckState] = {}
# Uno alla volta: due letture complete in parallelo dallo stesso disco
# rallentano entrambe (e il client che sta facendo seed).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="full-check")


def _result_dict(result: CheckResult) -> dict:
    data = asdict(result)
    data["percent"] = result.percent
    return data


# Chiamato nel worker, con la sua sessione, a controllo finito: result è
# None se il controllo non è arrivato in fondo (errore o annullato).
AfterCheck = Callable[[Session, "CheckState", CheckResult | None], None]


def _run(session_factory: sessionmaker, state: CheckState, fetch_torrent=None, after: AfterCheck | None = None) -> None:
    if state.cancel_requested:
        state.status, state.finished_at = "cancelled", datetime.now(UTC)
        if after is not None:
            session = session_factory()
            try:
                after(session, state, None)
            finally:
                session.close()
        return
    state.status = "running"
    session = session_factory()
    try:
        candidate = session.get(Candidate, state.candidate_id)
        seed_job = session.get(SeedJob, state.seed_job_id) if state.seed_job_id else None
        if candidate is None:
            raise FullCheckError("Candidate not found")

        def on_start(total: int) -> None:
            state.bytes_total = total

        def on_progress(done: int) -> None:
            state.bytes_done = done

        result = run_full_check(
            session, candidate, seed_job, state.media_file_id, fetch_torrent,
            on_start=on_start, on_progress=on_progress, cancelled=lambda: state.cancel_requested,
        )
        state.result = _result_dict(result)
        passed, reason = verdict(result)
        state.verdict, state.verdict_reason = ("passed" if passed else "failed"), reason
        logger.info(
            "Controllo completo di %r: %d/%d piece validi (%d diversi, %d non leggibili)",
            state.label, result.ok, result.pieces, result.mismatched, result.unreadable,
        )
        if after is not None:
            after(session, state, result)
        state.status = "done"
    except CheckCancelled:
        state.status = "cancelled"
        if after is not None:
            session.rollback()
            after(session, state, None)
    except Exception as exc:
        logger.warning("Controllo completo di %r fallito", state.label, exc_info=True)
        state.status, state.error = "failed", str(exc)
        if after is not None:
            try:
                session.rollback()
                after(session, state, None)
            except Exception:
                logger.exception("Aggiornamento dopo il controllo fallito di %r non riuscito", state.label)
    finally:
        state.finished_at = datetime.now(UTC)
        session.close()


def start_check(session_factory: sessionmaker, session: Session, candidate_id: int, seed_job_id: int | None = None,
                media_file_id: int | None = None, fetch_torrent=None, *, purpose: str = "manual",
                review_id: int | None = None, after: AfterCheck | None = None) -> CheckState:
    candidate = session.get(Candidate, candidate_id)
    if candidate is None:
        raise FullCheckError("Candidate not found")
    if seed_job_id is not None:
        seed_job = session.get(SeedJob, seed_job_id)
        if seed_job is None or seed_job.candidate_id != candidate_id:
            raise FullCheckError("This execution doesn't belong to the candidate")
    state = CheckState(
        id=uuid.uuid4().hex[:12], candidate_id=candidate_id, seed_job_id=seed_job_id,
        media_file_id=media_file_id, label=candidate.name, purpose=purpose, review_id=review_id,
    )
    with _lock:
        _checks[state.id] = state
        finished = sorted((c for c in _checks.values() if c.finished_at), key=lambda c: c.finished_at)
        for old in finished[: max(len(_checks) - MAX_KEPT_CHECKS, 0)]:
            _checks.pop(old.id, None)
    _executor.submit(_run, session_factory, state, fetch_torrent, after)
    return state


def get_check(check_id: str) -> CheckState | None:
    with _lock:
        return _checks.get(check_id)


def list_checks() -> list[CheckState]:
    with _lock:
        return sorted(_checks.values(), key=lambda c: c.created_at, reverse=True)


def cancel_check(check_id: str) -> CheckState | None:
    state = get_check(check_id)
    if state is not None and state.status in ("queued", "running"):
        state.cancel_requested = True
    return state
