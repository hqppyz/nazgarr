"""Coda di revisione: crea e gestisce le righe match_review.

Vedi docs/SPEC.md sezione 8. Ogni file orfano (media_file o seed_file)
produce al massimo UNA riga di review, sul suo candidate a confidence più
alta — le alternative restano visibili in `candidate` per audit ma non
generano righe di review proprie. Sopra soglia -> auto_approved, cioè
"consigliata": viene eseguita da sola SOLO se l'utente ha acceso
l'esecuzione automatica (auto_execute_enabled, spenta di default),
altrimenti aspetta la sua approvazione come le altre (approve()).
Sotto soglia ma con un candidato plausibile -> pending.
Nessun candidato plausibile (confidence 0.0 per tutti) -> nessuna riga di
review, niente da decidere.

Soglie separate per le due direzioni (docs/SPEC.md sezione 3): per
torrent_to_client il rischio di un match sbagliato è diverso (si aggiunge
un torrent a un file che esiste già, non si crea un hardlink su dati
sbagliati), ma trattato con la stessa severità — soglia più alta di
default, mai un bypass "perché il file esiste già"."""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import full_check
from app.adapter_factory import build_torrent_client_adapter
from app.exclusions import load_exclusions
from app.executor import ExecutionError, execute_review, reconcile_seed_job, retry_seed_job
from app.hardlinks import media_links
from app.models import (
    Candidate,
    ClientTorrent,
    ClientTorrentFile,
    MatchReview,
    MediaFile,
    SeedFile,
    SeedJob,
    TorrentClient,
)
from app.run_progress import NULL_PROGRESS
from app.scan_state import is_current, latest_scan_by_disk
from app.seed_refresh import refresh_seeded_torrent
from app.settings_repo import get_setting

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE_THRESHOLD_MEDIA_TO_TORRENT = 0.95
DEFAULT_CONFIDENCE_THRESHOLD_TORRENT_TO_CLIENT = 0.98

READY_FOR_DECISION_STATUSES = ("pending", "auto_approved")


def get_confidence_threshold(session: Session, direction: str) -> float:
    key = f"confidence_threshold_auto_{direction}"
    default = (
        DEFAULT_CONFIDENCE_THRESHOLD_MEDIA_TO_TORRENT
        if direction == "media_to_torrent"
        else DEFAULT_CONFIDENCE_THRESHOLD_TORRENT_TO_CLIENT
    )
    raw = get_setting(session, key)
    return float(raw) if raw is not None else default


def _supersede_active_reviews(session: Session, *, media_file_id: int | None, seed_file_id: int | None) -> int:
    """Marca come 'rejected' ogni review ancora attiva per lo stesso file
    orfano. Senza questo, ogni nuovo run che rimatcha lo stesso file
    aggiungerebbe una nuova review lasciando quella vecchia in coda per
    sempre — mai più di una valutazione attiva alla volta per lo stesso file."""
    query = session.query(MatchReview).filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES))
    if media_file_id is not None:
        query = query.filter(MatchReview.media_file_id == media_file_id)
    else:
        query = query.filter(MatchReview.seed_file_id == seed_file_id)
    stale = query.all()
    for review in stale:
        review.status = "rejected"
        review.decided_by = "system"
        review.decided_at = datetime.now(UTC)
    if stale:
        session.commit()
    return len(stale)


def _user_rejected_torrents(
    session: Session, *, media_file_id: int | None, seed_file_id: int | None
) -> set[tuple[int, str]]:
    """(tracker_id, torrent_id_remote) che l'utente ha già rifiutato per
    questo file. Le review rifiutate dal sistema (superate da una run più
    recente, vedi _supersede_active_reviews) non contano: solo una
    decisione umana esplicita è un "no" da ricordare."""
    query = (
        session.query(Candidate.tracker_id, Candidate.torrent_id_remote)
        .join(MatchReview, MatchReview.candidate_id == Candidate.id)
        .filter(MatchReview.status == "rejected", MatchReview.decided_by != "system")
    )
    if media_file_id is not None:
        query = query.filter(MatchReview.media_file_id == media_file_id)
    else:
        query = query.filter(MatchReview.seed_file_id == seed_file_id)
    return {(tracker_id, remote) for tracker_id, remote in query.all()}


def hashes_in_clients(session: Session) -> set[str]:
    """Info hash (minuscoli) dei torrent oggi presenti in un client."""
    return {(row[0] or "").lower() for row in session.query(ClientTorrent.info_hash).all()}


def seed_job_display_status(seed_job: SeedJob, in_client: set[str]) -> str:
    """final_status, tranne un'esecuzione riuscita il cui torrent l'utente
    ha poi tolto dal client: "removed" (solo per l'interfaccia, il seed_job
    resta com'è nel DB)."""
    if seed_job.final_status == "seeding" and (seed_job.info_hash or "").lower() not in in_client:
        return "removed"
    return seed_job.final_status


def _torrents_already_in_progress(
    session: Session, *, media_file_id: int | None, seed_file_id: int | None
) -> set[tuple[int, str]]:
    """(tracker_id, torrent_id_remote) già in coda o in esecuzione per un
    ALTRO file: un season pack scoperto dall'episodio 1 non deve rientrare
    in coda dall'episodio 2 (stessa decisione, stesso seed). Per lo stesso
    file vale invece la regola di sempre: la review nuova sostituisce la
    vecchia (_supersede_active_reviews)."""
    active = (
        session.query(Candidate.tracker_id, Candidate.torrent_id_remote, MatchReview.media_file_id,
                      MatchReview.seed_file_id)
        .join(MatchReview, MatchReview.candidate_id == Candidate.id)
        .filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES + ("approved",)))
        .all()
    )
    running = (
        session.query(Candidate.tracker_id, Candidate.torrent_id_remote, SeedJob.source_media_file_id,
                      SeedJob.source_seed_file_id, SeedJob.final_status, SeedJob.info_hash)
        .join(SeedJob, SeedJob.candidate_id == Candidate.id)
        .filter(SeedJob.final_status.in_(("in_progress", "seeding")))
        .all()
    )
    # Un'esecuzione "seeding" il cui torrent l'utente ha poi rimosso dal
    # client non occupa più quel torrent: si deve poter riproporre.
    in_client = hashes_in_clients(session)
    running = [
        (tracker_id, remote, mf_id, sf_id)
        for tracker_id, remote, mf_id, sf_id, status, info_hash in running
        if status == "in_progress" or (info_hash or "").lower() in in_client
    ]
    return {
        (tracker_id, remote)
        for tracker_id, remote, mf_id, sf_id in [*active, *running]
        if (mf_id, sf_id) != (media_file_id, seed_file_id)
    }


def _create_review(
    session: Session, candidates: list[Candidate], *, media_file_id: int | None, seed_file_id: int | None
) -> MatchReview | None:
    # Un torrent già rifiutato dall'utente per questo file non torna mai in
    # coda a ogni nuova ricerca — resta solo nell'audit trail di candidate.
    rejected = _user_rejected_torrents(session, media_file_id=media_file_id, seed_file_id=seed_file_id)
    busy = _torrents_already_in_progress(session, media_file_id=media_file_id, seed_file_id=seed_file_id)
    candidates = [c for c in candidates if (c.tracker_id, c.torrent_id_remote) not in rejected | busy]
    if not candidates:
        return None

    _supersede_active_reviews(session, media_file_id=media_file_id, seed_file_id=seed_file_id)

    best = max(candidates, key=lambda c: c.confidence)
    if best.confidence <= 0.0:
        return None

    direction = best.direction
    threshold = get_confidence_threshold(session, direction)
    if best.confidence >= threshold:
        review = MatchReview(
            candidate_id=best.id, media_file_id=media_file_id, seed_file_id=seed_file_id,
            status="auto_approved", decided_by="system", decided_at=datetime.now(UTC),
        )
    else:
        review = MatchReview(
            candidate_id=best.id, media_file_id=media_file_id, seed_file_id=seed_file_id, status="pending"
        )

    session.add(review)
    session.commit()
    return review


def create_review_for_media_file(
    session: Session, media_file: MediaFile, candidates: list[Candidate]
) -> MatchReview | None:
    return _create_review(session, candidates, media_file_id=media_file.id, seed_file_id=None)


def create_review_for_seed_file(
    session: Session, seed_file: SeedFile, candidates: list[Candidate]
) -> MatchReview | None:
    return _create_review(session, candidates, media_file_id=None, seed_file_id=seed_file.id)


def _build_torrent_client_adapter_or_none(session: Session):
    """Ritorna (adapter, torrent_client_id) — l'id serve a executor.py per
    risolvere l'eventuale path override specifico di QUESTO client per il
    disco coinvolto (disk_torrent_client.torrent_client_root_path, non un
    campo del disco). (None, None) se nessun client abilitato."""
    torrent_client_row = session.query(TorrentClient).filter_by(enabled=True).first()
    if torrent_client_row is None:
        logger.info("Nessun client torrent configurato: esecuzione rimandata")
        return None, None
    return build_torrent_client_adapter(torrent_client_row), torrent_client_row.id


def _client_for(session: Session, preferred_id: int | None):
    """(adapter, torrent_client_id) del client indicato se esiste ed è
    abilitato, altrimenti del primo client abilitato (comportamento di
    sempre). (None, None) se nessun client è abilitato."""
    if preferred_id is not None:
        row = session.get(TorrentClient, preferred_id)
        if row is not None and row.enabled:
            return build_torrent_client_adapter(row), row.id
    return _build_torrent_client_adapter_or_none(session)


def _client_for_candidate(session: Session, candidate: Candidate):
    """Il client scelto per il tracker del candidato (Configuration >
    Integrations > tracker), o il primo client abilitato."""
    tracker = candidate.tracker
    return _client_for(session, tracker.torrent_client_id if tracker is not None else None)


def _try_execute(session: Session, review: MatchReview, skip_recheck: bool = False) -> None:
    adapter, torrent_client_id = _client_for_candidate(session, review.candidate)
    if adapter is None:
        return
    try:
        execute_review(session, review, adapter, torrent_client_id, skip_recheck=skip_recheck)
    except ExecutionError:
        logger.exception(
            "Esecuzione immediata fallita per review %s (visibile tra le esecuzioni fallite, ritenta da lì)",
            review.id,
        )
    except Exception:
        logger.exception("Errore inatteso nell'esecuzione immediata per review %s", review.id)


VERIFY_SETTING = "verify_before_execute"


SKIP_RECHECK_SETTING = "skip_client_recheck_when_verified"


def skip_recheck_enabled(session: Session) -> bool:
    """Spenta di default. Accesa, e solo con la verifica completa accesa, un
    torrent verificato al 100% dal controllo di Nazgarr entra nel client
    senza il suo recheck (unica eccezione alla regola "sempre un recheck
    reale", decisione dell'utente del 2026-09-29, vedi CLAUDE.md)."""
    return (
        (get_setting(session, SKIP_RECHECK_SETTING) or "").lower() == "true"
        and verify_before_execute_enabled(session)
    )


def fully_verified(result, candidate) -> bool:
    """Il controllo dà il 100% dei piece, senza extra da scaricare (nessun
    piece illeggibile) e sul torrent giusto: solo così il recheck del client
    si può saltare. Con un extra mancante il client DEVE fare il recheck e
    scaricarlo, altrimenti lo crederebbe completo."""
    return (
        result.pieces > 0 and result.ok == result.pieces and result.mismatched == 0 and result.unreadable == 0
        and (not candidate.info_hash or candidate.info_hash.lower() == result.info_hash.lower())
    )


def verify_before_execute_enabled(session: Session) -> bool:
    """Attiva di default (decisione dell'utente): prima di creare hardlink o
    aggiungere un torrent, il controllo completo dei piece (app/full_check.py)
    deve dire che il recheck del client riuscirà. Si spegne da
    Configuration > Matching & approval per chi preferisce la velocità."""
    return (get_setting(session, VERIFY_SETTING) or "true").lower() != "false"


class AlreadyVerifyingError(Exception):
    pass


def request_approval(session: Session, review: MatchReview, session_factory, decided_by: str = "user",
                     fetch_torrent=None) -> MatchReview:
    """Approve dall'interfaccia. Con la verifica attiva la review resta in
    coda come "verifying" e parte il controllo completo in background:
    l'approvazione e l'esecuzione arrivano solo se passa (_after_verification).
    Senza verifica, come sempre: approva ed esegue subito."""
    if not verify_before_execute_enabled(session):
        return approve(session, review, decided_by=decided_by)
    if review.verify_status == "verifying":
        raise AlreadyVerifyingError(f"Review {review.id} is already being verified")

    def after(worker_session: Session, state, result) -> None:
        _after_verification(worker_session, state, result, decided_by)

    state = full_check.start_check(
        session_factory, session, review.candidate_id, media_file_id=review.media_file_id,
        fetch_torrent=fetch_torrent, purpose="verify", review_id=review.id, after=after,
    )
    review.verify_status, review.verify_detail, review.verify_check_id = "verifying", None, state.id
    session.commit()
    return review


def _after_verification(session: Session, state, result, decided_by: str) -> None:
    review = session.get(MatchReview, state.review_id)
    if review is None:
        state.execution = "skipped"
        return
    if result is None:  # controllo non arrivato in fondo: torna in coda com'era
        cancelled = state.status == "cancelled"
        review.verify_status = None if cancelled else "failed"
        review.verify_detail = None if cancelled else f"The check could not run: {state.error}"
        state.execution = "skipped"
        session.commit()
        return
    if state.verdict != "passed":
        review.verify_status, review.verify_detail = "failed", state.verdict_reason
        state.execution = "skipped"
        session.commit()
        logger.info("Review %s: controllo completo non superato (%s), niente eseguito", review.id, state.verdict_reason)
        return
    review.verify_status = "passed"
    review.verify_detail = f"{result.ok} of {result.pieces} pieces verified"
    session.commit()
    if review.status not in READY_FOR_DECISION_STATUSES:
        # Nel frattempo una run l'ha superata o chiusa: niente esecuzione.
        state.execution = "skipped"
        return
    state.stage = "executing"
    skip = skip_recheck_enabled(session) and fully_verified(result, review.candidate)
    approve(session, review, decided_by=decided_by, skip_recheck=skip)
    seed_job = (
        session.query(SeedJob).filter_by(candidate_id=review.candidate_id).order_by(SeedJob.id.desc()).first()
    )
    if seed_job is None:
        state.execution = "no_client"
    elif seed_job.final_status == "failed":
        state.execution, state.execution_error = "failed", seed_job.error_message
    else:
        state.execution = "added"


def reset_interrupted_verifications(session: Session) -> int:
    """All'avvio: un controllo "verifying" era in memoria in un processo che
    non c'è più. La review torna in coda com'era, da approvare di nuovo."""
    rows = session.query(MatchReview).filter(MatchReview.verify_status == "verifying").all()
    for row in rows:
        row.verify_status, row.verify_detail, row.verify_check_id = None, None, None
    if rows:
        session.commit()
    return len(rows)


def approve(
    session: Session, review: MatchReview, decided_by: str = "user", skip_recheck: bool = False,
) -> MatchReview:
    """Approva e prova subito l'esecuzione (hardlink+seed, o solo add al
    client) se un client torrent è configurato. Un fallimento
    dell'esecuzione non annulla l'approvazione: resta approved con il
    seed_job in stato failed — ritenta da list_failed_seed_jobs()."""
    review.status = "approved"
    review.decided_by = decided_by
    review.decided_at = datetime.now(UTC)
    session.commit()
    if skip_recheck:
        _try_execute(session, review, skip_recheck=True)
    else:
        _try_execute(session, review)
    return review


def reject(session: Session, review: MatchReview, decided_by: str = "user") -> MatchReview:
    review.status = "rejected"
    review.decided_by = decided_by
    review.decided_at = datetime.now(UTC)
    session.commit()
    return review


def _identity_changed(review: MatchReview, mf: MediaFile) -> bool:
    """Il candidato era stato cercato per un contenuto che il file non è più
    (identità corretta da Radarr/Sonarr o da una rilettura del nome): quel
    torrent è di un altro film/episodio, la review non ha più senso."""
    candidate = review.candidate
    return (candidate is not None and mf.media_item_id is not None
            and candidate.media_item_id != mf.media_item_id)


def close_resolved_reviews(session: Session) -> int:
    """Chiude (rifiuto di sistema, mai contato come un "no" dell'utente, vedi
    _user_rejected_torrents) le review ancora in coda il cui file non ha più
    bisogno di niente: libreria -> torrent con un hardlink ormai presente,
    torrent -> client con il file ormai tracciato da un client, un file
    non più presente sul disco o la cui identità è cambiata. Senza questo, una review restava in coda
    per sempre: il matching sostituisce solo le review dei file che ricerca,
    e un file non più orfano non lo ricerca più. Anche un file ora escluso
    esce dalla coda. Chiamata dalla pipeline
    dopo scan e indicizzazione, prima del matching."""
    active = [
        r for r in session.query(MatchReview).filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES)).all()
        if not session.query(SeedJob).filter_by(candidate_id=r.candidate_id).count()
    ]
    if not active:
        return 0
    hardlinked = set(media_links(session))
    tracked = {
        row[0]
        for row in session.query(ClientTorrentFile.seed_file_id)
        .filter(ClientTorrentFile.seed_file_id.isnot(None))
        .all()
    }
    latest_media = latest_scan_by_disk(session, MediaFile)
    latest_seed = latest_scan_by_disk(session, SeedFile)
    exclusions = load_exclusions(session)
    closed = 0
    for review in active:
        # Un file escluso nel frattempo è fuori da ogni controllo: anche la
        # sua review esce dalla coda.
        if review.media_file_id is not None:
            mf = review.media_file
            resolved = (mf is None or not is_current(mf, latest_media) or mf.id in hardlinked
                        or exclusions.is_excluded(mf.relative_path) or _identity_changed(review, mf))
        else:
            sf = review.seed_file
            resolved = (sf is None or not is_current(sf, latest_seed) or sf.id in tracked
                        or exclusions.is_excluded(sf.relative_path))
        if resolved:
            review.status = "rejected"
            review.decided_by = "system"
            review.decided_at = datetime.now(UTC)
            closed += 1
    if closed:
        session.commit()
        logger.info("%d review chiuse: il loro file non è più orfano o non esiste più", closed)
    return closed


AUTO_EXECUTE_SETTING = "auto_execute_above_threshold"


def auto_execute_enabled(session: Session) -> bool:
    """Spenta di default, e resta spenta finché l'utente non la accende
    esplicitamente (Configuration > Matching & approval). Decisione dell'utente: niente
    che modifichi file o client (hardlink, torrent aggiunti) parte senza
    una sua approvazione. Sopra soglia una review è solo "consigliata"
    (status auto_approved) e aspetta in coda come le altre."""
    return (get_setting(session, AUTO_EXECUTE_SETTING) or "").lower() == "true"


def execute_auto_approved(session: Session, progress=NULL_PROGRESS) -> dict[str, int]:
    """Esegue le review sopra soglia (auto_approved) senza ancora un
    seed_job — SOLO se l'utente ha acceso l'esecuzione automatica, mai di
    default (auto_execute_enabled). Le 'pending' non vengono mai eseguite
    qui. Chiamata da app/pipeline.py dopo il matching di ogni run."""
    reviews = [
        r
        for r in session.query(MatchReview).filter(MatchReview.status == "auto_approved").all()
        if not session.query(SeedJob).filter_by(candidate_id=r.candidate_id).count()
    ]
    if not auto_execute_enabled(session):
        progress.detail(f"Automatic execution is off: {len(reviews)} recommended, waiting for your approval")
        return {"executed": 0, "waiting": len(reviews)}
    progress.add_total(len(reviews))
    verify = verify_before_execute_enabled(session)
    executed = 0
    for review in reviews:
        verified = _verify_now(session, review, progress) if verify else None
        if verify and not verified:
            progress.advance()
            continue
        skip = verified is not None and skip_recheck_enabled(session) and fully_verified(verified, review.candidate)
        approve(session, review, decided_by="system", skip_recheck=skip)
        executed += 1
        progress.advance()
        progress.result(executed=1)
    return {"executed": executed, "waiting": 0}


def _verify_now(session: Session, review: MatchReview, progress):
    """Esecuzione automatica con la verifica attiva: lo stesso controllo
    completo, qui nella run (già in background) invece che nel worker."""
    progress.detail(f"Verifying {review.candidate.name}")
    try:
        result = full_check.run_full_check(session, review.candidate, None, review.media_file_id)
    except Exception as exc:
        review.verify_status, review.verify_detail = "failed", f"The check could not run: {exc}"
        session.commit()
        return None
    passed, reason = full_check.verdict(result)
    review.verify_status = "passed" if passed else "failed"
    review.verify_detail = f"{result.ok} of {result.pieces} pieces verified" if passed else reason
    session.commit()
    return result if passed else None


def list_ready_for_review(session: Session) -> list[MatchReview]:
    """match_review in attesa di una decisione (pending o auto_approved) il
    cui candidate non ha ancora un seed_job — esclude quelle già eseguite
    (con successo o meno) in un tentativo precedente."""
    reviews = session.query(MatchReview).filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES)).all()
    return [
        r
        for r in reviews
        if not session.query(SeedJob).filter_by(candidate_id=r.candidate_id).count()
    ]


def approve_all(session: Session, decided_by: str = "user") -> int:
    reviews = list_ready_for_review(session)
    for review in reviews:
        approve(session, review, decided_by=decided_by)
    return len(reviews)


def list_failed_seed_jobs(session: Session) -> list[SeedJob]:
    return session.query(SeedJob).filter_by(final_status="failed").all()


def retry_failed(session: Session, seed_job: SeedJob) -> SeedJob:
    # Col client dove era stato aggiunto, se si sa; altrimenti quello del tracker.
    adapter, torrent_client_id = (
        _client_for(session, seed_job.torrent_client_id)
        if seed_job.torrent_client_id is not None
        else _client_for_candidate(session, seed_job.candidate)
    )
    if adapter is None:
        raise ExecutionError("Nessun client torrent configurato")
    return retry_seed_job(session, seed_job, adapter, torrent_client_id)


def retry_all_failed(session: Session) -> dict[str, int]:
    seed_jobs = list_failed_seed_jobs(session)
    succeeded = 0
    failed = 0
    for seed_job in seed_jobs:
        try:
            result = retry_failed(session, seed_job)
        except ExecutionError:
            logger.exception("Retry fallito per seed_job %s", seed_job.id)
            failed += 1
            continue
        if result.final_status == "failed":
            failed += 1
        else:
            succeeded += 1
    return {"succeeded": succeeded, "failed": failed}


def reconcile_pending_seed_jobs(session: Session, progress=NULL_PROGRESS) -> dict[str, int]:
    """Ricontrolla lo stato reale nel client per ogni seed_job ancora
    'in_progress' con un info_hash già noto — una sola interrogazione di
    stato per client (mai un hardlink o un add_torrent), quindi non viola
    la regola "nessuna esecuzione senza conferma umana". Un seed appena
    passato a "seeding" viene reso subito visibile nelle viste
    (app/seed_refresh.py) invece di aspettare la run successiva. Chiamata a
    fine run e, fra una run e l'altra, dallo scheduler ogni pochi minuti."""
    pending = (
        session.query(SeedJob)
        .filter(SeedJob.final_status == "in_progress")
        .filter(SeedJob.info_hash.isnot(None))
        .all()
    )
    reconciled = 0
    errors = 0
    progress.add_total(len(pending))
    # Ogni seed job nel client in cui è stato aggiunto (seed job vecchi senza
    # client registrato: quello del tracker, o il primo abilitato). Un adapter
    # per client, non uno per job.
    adapters: dict[int | None, tuple] = {}
    for seed_job in pending:
        progress.advance()
        key = seed_job.torrent_client_id if seed_job.torrent_client_id is not None else -seed_job.candidate.tracker_id
        if key not in adapters:
            adapters[key] = (
                _client_for(session, seed_job.torrent_client_id)
                if seed_job.torrent_client_id is not None
                else _client_for_candidate(session, seed_job.candidate)
            )
        adapter, torrent_client_id = adapters[key]
        if adapter is None:
            continue
        try:
            reconcile_seed_job(session, seed_job, adapter)
            reconciled += 1
        except Exception:
            logger.exception("Reconcile fallito per seed_job %s", seed_job.id)
            errors += 1
            continue
        if seed_job.final_status == "seeding":
            try:
                refresh_seeded_torrent(session, seed_job, adapter, torrent_client_id)
            except Exception:
                # Solo la visibilità immediata: la run successiva registra comunque tutto.
                logger.exception("Aggiornamento mirato fallito per seed_job %s", seed_job.id)
                session.rollback()
    return {"reconciled": reconciled, "errors": errors}


def has_pending_seed_jobs(session: Session) -> bool:
    return (
        session.query(SeedJob.id)
        .filter(SeedJob.final_status == "in_progress", SeedJob.info_hash.isnot(None))
        .first()
        is not None
    )
