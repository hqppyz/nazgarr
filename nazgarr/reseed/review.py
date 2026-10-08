"""Coda di revisione: crea e gestisce le righe match_review.

Vedi docs/SPEC.md sezione 8. Ogni file orfano (media_file o seed_file)
produce al massimo UNA riga di review per tracker, sul suo candidate a
confidence più alta — le alternative restano visibili in `candidate` per
audit ma non generano righe di review proprie. Per un episodio vince il
pack, se ce n'è uno plausibile (decisione dell'utente, 2026-10-08: di
solito, uscito il pack, i singoli non si caricano più); con "pack e singoli
dello stesso tracker" acceso le review sono una per formato
(nazgarr/library/seeding.py). Sopra soglia -> auto_approved, cioè
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

from sqlalchemy import exists
from sqlalchemy.orm import Session

from nazgarr.core import settings_registry
from nazgarr.core.models import (
    Candidate,
    CandidateFile,
    ClientTorrent,
    ClientTorrentFile,
    MatchAttempt,
    MatchReview,
    MediaFile,
    SeedFile,
    SeedJob,
    TorrentClient,
    Tracker,
)
from nazgarr.core.run_progress import NULL_PROGRESS
from nazgarr.integrations.adapter_factory import build_torrent_client_adapter, close_adapter
from nazgarr.library.exclusions import load_exclusions
from nazgarr.library.scan_state import is_current, latest_scan_by_disk
from nazgarr.library.seed_refresh import refresh_seeded_torrent
from nazgarr.library.seeding import (
    FORMATS,
    PACK,
    SINGLE,
    is_episode,
    pack_and_singles_enabled,
    seeding_formats,
    seeding_media_file_ids,
    torrent_format,
)
from nazgarr.reseed import full_check
from nazgarr.reseed.executor import ExecutionError, execute_review, reconcile_seed_job, retry_seed_job
from nazgarr.torrents import client_labels

logger = logging.getLogger(__name__)


READY_FOR_DECISION_STATUSES = ("pending", "auto_approved")


def get_confidence_threshold(session: Session, direction: str) -> float:
    return settings_registry.get_float(session, f"confidence_threshold_auto_{direction}")


def candidate_format(candidate: Candidate) -> str:
    """"pack" (più video) o "single" (un video, anche con extra)."""
    return torrent_format(sum(1 for f in candidate.files if f.is_video))


def _reject_by_system(session: Session, reviews: list[MatchReview]) -> int:
    for review in reviews:
        review.status = "rejected"
        review.decided_by = "system"
        review.decided_at = datetime.now(UTC)
    if reviews:
        session.commit()
    return len(reviews)


def _supersede_active_reviews(
    session: Session, *, media_file_id: int | None, seed_file_id: int | None, tracker_id: int | None = None,
    formats: frozenset[str] = FORMATS,
) -> int:
    """Marca come 'rejected' ogni review ancora attiva per lo stesso file
    orfano sullo stesso tracker. Senza questo, ogni nuovo run che rimatcha lo
    stesso file aggiungerebbe una nuova review lasciando quella vecchia in
    coda per sempre — mai più di una valutazione attiva alla volta per file e
    tracker. Per tracker e non per file: con i cross-seed (nazgarr/library/seeding.py) lo
    stesso file può avere una proposta su ogni tracker. formats: solo le
    review di questi formati, quelli appena cercati (con "pack e singoli" un
    episodio ha una proposta per formato)."""
    query = session.query(MatchReview).filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES))
    if tracker_id is not None:
        query = query.join(Candidate, Candidate.id == MatchReview.candidate_id)
        query = query.filter(Candidate.tracker_id == tracker_id)
    if media_file_id is not None:
        query = query.filter(MatchReview.media_file_id == media_file_id)
    else:
        query = query.filter(MatchReview.seed_file_id == seed_file_id)
    return _reject_by_system(session, [r for r in query.all() if candidate_format(r.candidate) in formats])


def _user_rejected_torrents(
    session: Session, *, media_file_id: int | None, seed_file_id: int | None
) -> set[tuple[int, str]]:
    """(tracker_id, torrent_id_remote) che l'utente ha già rifiutato per
    questo file, anche come parte di un pack proposto per un altro episodio
    (lo stesso "no" per tutta la stagione). Le review rifiutate dal sistema
    (superate da una run più recente, vedi _supersede_active_reviews) non
    contano: solo una decisione umana esplicita è un "no" da ricordare."""
    rejected = (
        session.query(Candidate.tracker_id, Candidate.torrent_id_remote)
        .join(MatchReview, MatchReview.candidate_id == Candidate.id)
        .filter(MatchReview.status == "rejected", MatchReview.decided_by != "system")
    )
    if media_file_id is not None:
        own = rejected.filter(MatchReview.media_file_id == media_file_id)
        inside = rejected.join(CandidateFile, CandidateFile.candidate_id == Candidate.id).filter(
            CandidateFile.media_file_id == media_file_id)
    else:
        own = rejected.filter(MatchReview.seed_file_id == seed_file_id)
        inside = rejected.join(CandidateFile, CandidateFile.candidate_id == Candidate.id).filter(
            CandidateFile.seed_file_id == seed_file_id)
    return {(tracker_id, remote) for tracker_id, remote in [*own.all(), *inside.all()]}


def _covered_by_pack(session: Session, media_file_id: int, tracker_id: int) -> bool:
    """Un pack di questo tracker già in coda o approvato per un altro
    episodio contiene anche questo file: il singolo non serve (pack preferito)."""
    rows = (
        session.query(Candidate)
        .join(MatchReview, MatchReview.candidate_id == Candidate.id)
        .join(CandidateFile, CandidateFile.candidate_id == Candidate.id)
        .filter(Candidate.tracker_id == tracker_id, CandidateFile.media_file_id == media_file_id,
                MatchReview.media_file_id != media_file_id,
                MatchReview.status.in_(READY_FOR_DECISION_STATUSES + ("approved",)))
        .all()
    )
    return any(candidate_format(c) == PACK for c in rows)


def _supersede_singles_in_pack(session: Session, pack: Candidate) -> int:
    """Le proposte di singoli degli altri episodi del pack appena proposto,
    sullo stesso tracker, escono dalla coda (rifiuto di sistema)."""
    episodes = {f.media_file_id for f in pack.files if f.is_video and f.media_file_id is not None}
    if not episodes:
        return 0
    active = (
        session.query(MatchReview)
        .join(Candidate, Candidate.id == MatchReview.candidate_id)
        .filter(Candidate.tracker_id == pack.tracker_id, MatchReview.media_file_id.in_(episodes),
                MatchReview.status.in_(READY_FOR_DECISION_STATUSES), MatchReview.candidate_id != pack.id)
        .all()
    )
    return _reject_by_system(session, [r for r in active if candidate_format(r.candidate) == SINGLE])


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
    session: Session, *, media_file_id: int | None, seed_file_id: int | None, in_client: set[str] | None = None,
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
    in_client = hashes_in_clients(session) if in_client is None else in_client
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
    session: Session, candidates: list[Candidate], *, media_file_id: int | None, seed_file_id: int | None,
    in_client: set[str] | None = None, formats: frozenset[str] = FORMATS, both_formats: bool = False,
    prefer_pack: bool = False,
) -> MatchReview | None:
    """in_client: gli info hash nei client, se il chiamante li ha già letti
    (il matching li legge una volta per tracker invece che per ogni file).
    formats: quelli cercati per il file. Solo per un episodio: both_formats
    ("pack e singoli dello stesso tracker") fa una review per formato,
    prefer_pack una sola, col pack se ce n'è uno plausibile. Restituisce la
    prima creata (il pack, se c'è)."""
    if not candidates:
        return None  # il caso più comune nel matching: niente da leggere
    # Un torrent già rifiutato dall'utente per questo file non torna mai in
    # coda a ogni nuova ricerca — resta solo nell'audit trail di candidate.
    rejected = _user_rejected_torrents(session, media_file_id=media_file_id, seed_file_id=seed_file_id)
    in_client = hashes_in_clients(session) if in_client is None else in_client
    busy = _torrents_already_in_progress(
        session, media_file_id=media_file_id, seed_file_id=seed_file_id, in_client=in_client)
    # Un torrent già in un client (con un'altra copia dei file) non si può
    # aggiungere di nuovo: il client lo rifiuterebbe come duplicato.
    candidates = [
        c for c in candidates
        if (c.tracker_id, c.torrent_id_remote) not in rejected | busy and (c.info_hash or "").lower() not in in_client
    ]
    if not candidates:
        return None
    tracker_id = candidates[0].tracker_id
    if prefer_pack and _covered_by_pack(session, media_file_id, tracker_id):
        candidates = [c for c in candidates if candidate_format(c) == PACK]

    _supersede_active_reviews(
        session, media_file_id=media_file_id, seed_file_id=seed_file_id, tracker_id=tracker_id, formats=formats,
    )

    plausible = [c for c in candidates if c.confidence > 0.0]
    if not plausible:
        return None
    packs = [c for c in plausible if candidate_format(c) == PACK]
    if both_formats:
        singles = [c for c in plausible if candidate_format(c) == SINGLE]
        picks = [max(group, key=lambda c: c.confidence) for group in (packs, singles) if group]
    elif prefer_pack:
        picks = [max(packs or plausible, key=lambda c: c.confidence)]
    else:
        picks = [max(plausible, key=lambda c: c.confidence)]

    reviews = []
    for best in picks:
        threshold = get_confidence_threshold(session, best.direction)
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
        reviews.append(review)
    session.commit()
    if prefer_pack and candidate_format(picks[0]) == PACK:
        _supersede_singles_in_pack(session, picks[0])
    return reviews[0]


def create_review_for_media_file(
    session: Session, media_file: MediaFile, candidates: list[Candidate], in_client: set[str] | None = None,
    formats: frozenset[str] = FORMATS, both_formats: bool = False,
) -> MatchReview | None:
    # Un film con dei contenuti extra in video non è un pack: formati solo per gli episodi.
    episode = is_episode(media_file.media_item)
    return _create_review(session, candidates, media_file_id=media_file.id, seed_file_id=None, in_client=in_client,
                          formats=formats, both_formats=both_formats and episode,
                          prefer_pack=episode and not both_formats)


def create_review_for_seed_file(
    session: Session, seed_file: SeedFile, candidates: list[Candidate], in_client: set[str] | None = None,
) -> MatchReview | None:
    return _create_review(session, candidates, media_file_id=None, seed_file_id=seed_file.id, in_client=in_client)


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


def client_row_for_candidate(session: Session, candidate: Candidate) -> TorrentClient | None:
    """Il client dove andrà il reseed di questo candidato (come
    _client_for_candidate), senza costruirne l'adapter: per mostrarne
    categorie e tag nella coda."""
    tracker = candidate.tracker
    if tracker is not None and tracker.torrent_client_id is not None:
        row = session.get(TorrentClient, tracker.torrent_client_id)
        if row is not None and row.enabled:
            return row
    return session.query(TorrentClient).filter_by(enabled=True).first()


def set_client_labels(session: Session, review: MatchReview, category: str | None, tags: str | None) -> None:
    """Categoria e tag nel client scelti a mano per questo reseed: None
    torna ai default del client, "" vuol dire nessuno."""
    review.client_category = category.strip() if category is not None else None
    review.client_tags = ",".join(client_labels.split_tags(tags)) if tags is not None else None
    session.commit()


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
    finally:
        close_adapter(adapter)


VERIFY_SETTING = "verify_before_execute"


SKIP_RECHECK_SETTING = "skip_client_recheck_when_verified"


def skip_recheck_enabled(session: Session) -> bool:
    """Spenta di default. Accesa, e solo con la verifica completa accesa, un
    torrent verificato al 100% dal controllo di Nazgarr entra nel client
    senza il suo recheck (unica eccezione alla regola "sempre un recheck
    reale", decisione dell'utente del 2026-09-29, vedi CLAUDE.md)."""
    return (
        settings_registry.get_bool(session, SKIP_RECHECK_SETTING)
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
    aggiungere un torrent, il controllo completo dei piece (nazgarr/reseed/full_check.py)
    deve dire che il recheck del client riuscirà. Si spegne da
    Configuration > Matching & approval per chi preferisce la velocità."""
    return settings_registry.get_bool(session, VERIFY_SETTING)


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
    active = without_seed_job(session.query(MatchReview).filter(
        MatchReview.status.in_(READY_FOR_DECISION_STATUSES))).all()
    if not active:
        return 0
    # In seed davvero (un client lo segue), e con i cross-seed per tracker:
    # una review si chiude quando il file seeda sul tracker del suo candidato.
    # Con "pack e singoli", per un episodio, quando seeda lì nel formato della
    # review: in seed come singolo, la proposta del pack serve ancora.
    seeding_by_tracker: dict[int | None, set[int]] = {}
    formats_by_tracker: dict[int, dict[int, set[str]]] = {}
    both_formats = pack_and_singles_enabled(session)

    def seeding_for(tracker_id: int | None) -> set[int]:
        if tracker_id not in seeding_by_tracker:
            tracker = session.get(Tracker, tracker_id) if tracker_id is not None else None
            seeding_by_tracker[tracker_id] = seeding_media_file_ids(session, tracker)
        return seeding_by_tracker[tracker_id]

    def still_needed(review: MatchReview, mf: MediaFile, tracker_id: int | None) -> bool:
        if mf.id not in seeding_for(tracker_id):
            return True
        if not both_formats or tracker_id is None or not is_episode(mf.media_item):
            return False
        if tracker_id not in formats_by_tracker:
            formats_by_tracker[tracker_id] = seeding_formats(session, session.get(Tracker, tracker_id))
        here = formats_by_tracker[tracker_id].get(mf.id, set())
        return bool(here) and candidate_format(review.candidate) not in here

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
            tracker_id = review.candidate.tracker_id if review.candidate is not None else None
            resolved = (mf is None or not is_current(mf, latest_media) or not still_needed(review, mf, tracker_id)
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
    return settings_registry.get_bool(session, AUTO_EXECUTE_SETTING)


def execute_auto_approved(session: Session, progress=NULL_PROGRESS) -> dict[str, int]:
    """Esegue le review sopra soglia (auto_approved) senza ancora un
    seed_job — SOLO se l'utente ha acceso l'esecuzione automatica, mai di
    default (auto_execute_enabled). Le 'pending' non vengono mai eseguite
    qui. Chiamata da nazgarr/reseed/pipeline.py dopo il matching di ogni run."""
    reviews = without_seed_job(session.query(MatchReview).filter(MatchReview.status == "auto_approved")).all()
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


def without_seed_job(query):
    """Solo le review il cui candidato non ha ancora un seed_job: in SQL,
    invece di una query per review."""
    return query.filter(~exists().where(SeedJob.candidate_id == MatchReview.candidate_id))


def list_ready_for_review(session: Session) -> list[MatchReview]:
    """match_review in attesa di una decisione (pending o auto_approved) il
    cui candidate non ha ancora un seed_job — esclude quelle già eseguite
    (con successo o meno) in un tentativo precedente."""
    return without_seed_job(
        session.query(MatchReview).filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES))).all()


def approve_all(session: Session, decided_by: str = "user") -> int:
    reviews = list_ready_for_review(session)
    for review in reviews:
        approve(session, review, decided_by=decided_by)
    return len(reviews)


def list_failed_seed_jobs(session: Session) -> list[SeedJob]:
    return session.query(SeedJob).filter_by(final_status="failed").all()


# Le esecuzioni che si possono eliminare: una in seed resta, è il record
# di cosa Nazgarr ha aggiunto al client.
DELETABLE_SEED_JOB_STATUSES = ("failed", "in_progress")


def delete_seed_job(session: Session, seed_job: SeedJob) -> None:
    """Toglie un'esecuzione fallita o rimasta in corso, così il prossimo scan
    ripropone il torrent per quel file: un candidato con un seed_job non
    torna mai in coda (without_seed_job). Si tolgono anche la review che
    l'aveva lanciata (rifiutata dal sistema, che non blocca una nuova
    proposta) e l'ultimo tentativo di matching del file su quel tracker,
    altrimenti lo scan lo salterebbe fino a rematch_interval_days. Non
    tocca né il client né i file: un hardlink rimasto si riusa alla nuova
    esecuzione (stesso inode), un torrent ancora nel client va tolto dal
    client perché il candidato torni."""
    if seed_job.final_status not in DELETABLE_SEED_JOB_STATUSES:
        raise ExecutionError(f"SeedJob {seed_job.id} is {seed_job.final_status}: only failed or running ones")
    candidate = session.get(Candidate, seed_job.candidate_id)
    file_filter = (
        {"media_file_id": seed_job.source_media_file_id} if seed_job.source_media_file_id is not None
        else {"seed_file_id": seed_job.source_seed_file_id}
    )
    for row in (
        session.query(MatchReview).filter_by(candidate_id=seed_job.candidate_id, **file_filter)
        .filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES + ("approved",)))
    ):
        row.status, row.decided_by, row.decided_at = "rejected", "system", datetime.now(UTC)
    if candidate is not None:
        session.query(MatchAttempt).filter_by(tracker_id=candidate.tracker_id, **file_filter).delete()
    logger.info("Seed job %s (%s) eliminato su richiesta", seed_job.id, seed_job.final_status)
    session.delete(seed_job)
    session.commit()


def retry_failed(session: Session, seed_job: SeedJob) -> SeedJob:
    # Col client dove era stato aggiunto, se si sa; altrimenti quello del tracker.
    adapter, torrent_client_id = (
        _client_for(session, seed_job.torrent_client_id)
        if seed_job.torrent_client_id is not None
        else _client_for_candidate(session, seed_job.candidate)
    )
    if adapter is None:
        raise ExecutionError("Nessun client torrent configurato")
    try:
        return retry_seed_job(session, seed_job, adapter, torrent_client_id)
    finally:
        close_adapter(adapter)


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
    (nazgarr/library/seed_refresh.py) invece di aspettare la run successiva. Chiamata a
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
    try:
        for seed_job in pending:
            progress.advance()
            key = (seed_job.torrent_client_id if seed_job.torrent_client_id is not None
                   else -seed_job.candidate.tracker_id)
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
    finally:
        for adapter, _id in adapters.values():
            if adapter is not None:
                close_adapter(adapter)
    return {"reconciled": reconciled, "errors": errors}


def has_pending_seed_jobs(session: Session) -> bool:
    return (
        session.query(SeedJob.id)
        .filter(SeedJob.final_status == "in_progress", SeedJob.info_hash.isnot(None))
        .first()
        is not None
    )
