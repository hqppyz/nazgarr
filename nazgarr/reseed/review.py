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
from collections import Counter
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, selectinload

from nazgarr.core import settings_registry
from nazgarr.core.errors import CodedError
from nazgarr.core.logs import safe_error
from nazgarr.core.models import (
    Candidate,
    CandidateFile,
    ClientTorrent,
    ClientTorrentFile,
    MatchAttempt,
    MatchReview,
    MediaFile,
    MediaItem,
    RunLog,
    SeedFile,
    SeedJob,
    TorrentClient,
    Tracker,
    UploadTarget,
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
from nazgarr.reseed.executor import (
    ExecutionError,
    RetryRefused,
    adopt_for_retry,
    execute_review,
    lookup_torrent,
    missing_long_enough,
    reconcile_seed_job,
    retry_from_scratch,
    review_of,
    seen_in_client,
)
from nazgarr.torrents import client_labels
from nazgarr.upload.jobs import SEED_RECHECK_PENDING

logger = logging.getLogger(__name__)


READY_FOR_DECISION_STATUSES = ("pending", "auto_approved")


def get_confidence_threshold(session: Session, direction: str) -> float:
    return settings_registry.get_float(session, f"confidence_threshold_auto_{direction}")


def candidate_format(candidate: Candidate) -> str:
    """"pack" (più video) o "single" (un video, anche con extra)."""
    return torrent_format(sum(1 for f in candidate.files if f.is_video))


def _reject_by_system(session: Session, reviews: list[MatchReview], queue: "ReviewQueue | None" = None) -> int:
    for review in reviews:
        review.status = "rejected"
        review.decided_by = "system"
        review.decided_at = datetime.now(UTC)
    if reviews:
        session.commit()
        if queue is not None:
            queue.closed(reviews)
    return len(reviews)


def _active_reviews(
    session: Session, *, media_file_id: int | None, seed_file_id: int | None, tracker_id: int | None = None,
    formats: frozenset[str] = FORMATS,
) -> list[MatchReview]:
    """Le review ancora in coda per questo file orfano su questo tracker, nei
    formati indicati."""
    query = session.query(MatchReview).filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES))
    if tracker_id is not None:
        query = query.join(Candidate, Candidate.id == MatchReview.candidate_id)
        query = query.filter(Candidate.tracker_id == tracker_id)
    if media_file_id is not None:
        query = query.filter(MatchReview.media_file_id == media_file_id)
    else:
        query = query.filter(MatchReview.seed_file_id == seed_file_id)
    return [r for r in query.all() if candidate_format(r.candidate) in formats]


def _supersede_active_reviews(
    session: Session, *, media_file_id: int | None, seed_file_id: int | None, tracker_id: int | None = None,
    formats: frozenset[str] = FORMATS, queue: "ReviewQueue | None" = None,
) -> int:
    """Marca come 'rejected' ogni review ancora attiva per lo stesso file
    orfano sullo stesso tracker. Senza questo, ogni nuovo run che rimatcha lo
    stesso file aggiungerebbe una nuova review lasciando quella vecchia in
    coda per sempre — mai più di una valutazione attiva alla volta per file e
    tracker. Per tracker e non per file: con i cross-seed (nazgarr/library/seeding.py) lo
    stesso file può avere una proposta su ogni tracker. formats: solo le
    review di questi formati, quelli appena cercati (con "pack e singoli" un
    episodio ha una proposta per formato). queue: senza review di quel file
    su quel tracker nella coda del passaggio, nessuna query."""
    if queue is not None and tracker_id is not None and not queue.has_reviews(tracker_id, media_file_id,
                                                                              seed_file_id):
        return 0
    active = _active_reviews(session, media_file_id=media_file_id, seed_file_id=seed_file_id,
                             tracker_id=tracker_id, formats=formats)
    return _reject_by_system(session, active, queue)


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
                MatchReview.status.in_((*READY_FOR_DECISION_STATUSES, "approved")))
        .all()
    )
    return any(candidate_format(c) == PACK for c in rows)


def _supersede_singles_in_pack(session: Session, pack: Candidate, queue: "ReviewQueue | None" = None) -> int:
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
    return _reject_by_system(session, [r for r in active if candidate_format(r.candidate) == SINGLE], queue)


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


def _busy_rows(session: Session, in_client: set[str]) -> tuple[dict, list]:
    """(review attive per id, esecuzioni in corso) come (tracker_id,
    torrent_id_remote, media_file_id, seed_file_id): i torrent che una review
    in coda o approvata, o un'esecuzione, occupano già."""
    active = {
        review_id: (tracker_id, remote, mf_id, sf_id)
        for review_id, tracker_id, remote, mf_id, sf_id in (
            session.query(MatchReview.id, Candidate.tracker_id, Candidate.torrent_id_remote,
                          MatchReview.media_file_id, MatchReview.seed_file_id)
            .join(Candidate, Candidate.id == MatchReview.candidate_id)
            .filter(MatchReview.status.in_((*READY_FOR_DECISION_STATUSES, "approved")))
        )
    }
    running = (
        session.query(Candidate.tracker_id, Candidate.torrent_id_remote, SeedJob.source_media_file_id,
                      SeedJob.source_seed_file_id, SeedJob.final_status, SeedJob.info_hash)
        .join(SeedJob, SeedJob.candidate_id == Candidate.id)
        .filter(SeedJob.final_status.in_(("in_progress", "seeding")))
        .all()
    )
    # Un'esecuzione "seeding" il cui torrent l'utente ha poi rimosso dal
    # client non occupa più quel torrent: si deve poter riproporre.
    running = [
        (tracker_id, remote, mf_id, sf_id)
        for tracker_id, remote, mf_id, sf_id, status, info_hash in running
        if status == "in_progress" or (info_hash or "").lower() in in_client
    ]
    return active, running


def _busy_for(rows, media_file_id: int | None, seed_file_id: int | None) -> set[tuple[int, str]]:
    return {
        (tracker_id, remote)
        for tracker_id, remote, mf_id, sf_id in rows
        if (mf_id, sf_id) != (media_file_id, seed_file_id)
    }


def _torrents_already_in_progress(
    session: Session, *, media_file_id: int | None, seed_file_id: int | None, in_client: set[str] | None = None,
) -> set[tuple[int, str]]:
    """(tracker_id, torrent_id_remote) già in coda o in esecuzione per un
    ALTRO file: un season pack scoperto dall'episodio 1 non deve rientrare
    in coda dall'episodio 2 (stessa decisione, stesso seed). Per lo stesso
    file vale invece la regola di sempre: la review nuova sostituisce la
    vecchia (_supersede_active_reviews)."""
    active, running = _busy_rows(session, hashes_in_clients(session) if in_client is None else in_client)
    return _busy_for([*active.values(), *running], media_file_id, seed_file_id)


# Un upload in corso di pubblicazione o di aggiunta al client.
_UPLOADS_IN_FLIGHT = ("uploading", "seeding")


def _own_uploads(session: Session) -> tuple[set[tuple[int, str]], set[str]]:
    """I torrent che un upload di Nazgarr (o un reseed del flusso degli
    upload) sta mettendo in seed o ha appena messo in seed, non ancora
    indicizzati: (tracker_id, id sul tracker) e info hash. Il flusso degli
    upload aggiunge il torrent al client senza registrarlo fra quelli
    indicizzati, così fino alla run dopo il file sembrava orfano e "Cerca
    ora" proponeva di riaggiungere l'upload stesso (audit 2026-10-18). Solo
    in quella finestra: i target in corso, e quelli finiti senza errori dopo
    l'inizio dell'ultima run conclusa (l'ultima indicizzazione). Dopo, il
    torrent è fra quelli dei client, o l'utente l'ha tolto e va riproposto
    come ogni altro; un target fallito non ha messo niente in seed. Conta
    anche un target finito col torrent fermo in attesa del suo recheck
    (SEED_RECHECK_PENDING, il reseed del flusso degli upload): è nel client,
    e "Cerca ora" lo proponeva come un reseed da rifare (audit 2026-10-18)."""
    last_index = session.query(func.max(RunLog.started_at)).filter(RunLog.finished_at.isnot(None)).scalar()
    finished = (UploadTarget.status == "done") & (
        UploadTarget.error_message.is_(None) | (UploadTarget.error_message == SEED_RECHECK_PENDING))
    if last_index is not None:
        finished &= UploadTarget.finished_at > last_index
    rows = session.query(UploadTarget.tracker_id, UploadTarget.action, UploadTarget.torrent_id_remote,
                         UploadTarget.reseed_torrent_id, UploadTarget.info_hash).filter(
        UploadTarget.status.in_(_UPLOADS_IN_FLIGHT) | finished).all()
    remotes = {
        (tracker_id, remote if action != "reseed" else (remote or reseed_id))
        for tracker_id, action, remote, reseed_id, _hash in rows
    }
    return ({(tracker_id, remote) for tracker_id, remote in remotes if remote},
            {info_hash.lower() for *_rest, info_hash in rows if info_hash})


class ReviewQueue:
    """La coda vista da un passaggio di matching su un tracker: gli info hash
    nei client e i torrent già occupati, letti una volta sola invece che a
    ogni orfano (audit 2026-10-18: ogni orfano rileggeva tutte le review
    attive e le esecuzioni), e aggiornati qui a ogni review creata o chiusa.
    Durante il matching nessun'altra parte crea review (la ricerca mirata e
    quella dopo un import non girano durante una run, nazgarr/reseed/exclusive.py),
    ma il worker degli upload sì aggiunge torrent ai client: gli upload e
    i loro torrent si rileggono subito prima di creare ogni review
    (refresh_uploads)."""

    def __init__(self, session: Session, in_client: set[str] | None = None):
        self.in_client = hashes_in_clients(session) if in_client is None else in_client
        self._active, self._running = _busy_rows(session, self.in_client)
        self.uploaded, self.uploaded_hashes = _own_uploads(session)
        # Quante review attive o approvate ha ogni file su ogni tracker: per
        # non interrogare il DB per i file che non ne hanno (quasi tutti).
        self._by_file: Counter[tuple] = Counter((t, mf, sf) for t, _r, mf, sf in self._active.values())

    def busy_for(self, media_file_id: int | None, seed_file_id: int | None) -> set[tuple[int, str]]:
        return _busy_for([*self._active.values(), *self._running], media_file_id, seed_file_id)

    def has_reviews(self, tracker_id: int, media_file_id: int | None, seed_file_id: int | None) -> bool:
        return self._by_file[(tracker_id, media_file_id, seed_file_id)] > 0

    def opened(self, review: MatchReview, candidate: Candidate) -> None:
        self._active[review.id] = (candidate.tracker_id, candidate.torrent_id_remote, review.media_file_id,
                                   review.seed_file_id)
        self._by_file[(candidate.tracker_id, review.media_file_id, review.seed_file_id)] += 1

    def closed(self, reviews: list[MatchReview]) -> None:
        for review in reviews:
            entry = self._active.pop(review.id, None)
            if entry is not None:
                tracker_id, _remote, mf_id, sf_id = entry
                self._by_file[(tracker_id, mf_id, sf_id)] -= 1

    def refresh_uploads(self, session: Session, candidates: list[Candidate]) -> None:
        """Gli upload di Nazgarr e, fra gli info hash di questi candidati,
        quelli ora in un client, riletti adesso: il worker degli upload non
        aspetta le run, e un upload pubblicato e messo in seed durante il
        passaggio (letto all'inizio, prima che partisse) veniva proposto
        come un reseed da rifare, eseguito con l'esecuzione automatica
        accesa (audit 2026-10-18, revisione). Due query piccole, una volta
        per file con un candidato plausibile, mai per ogni orfano."""
        self.uploaded, self.uploaded_hashes = _own_uploads(session)
        self.in_client |= _now_in_clients(session, {c.info_hash for c in candidates if c.info_hash})


def _now_in_clients(session: Session, hashes: set[str]) -> set[str]:
    """Quali di questi info hash sono ora in un client (in minuscolo). Un
    client può riportarli in maiuscolo (rTorrent): si cercano in entrambe le
    forme, senza leggere tutti i torrent dei client."""
    if not hashes:
        return set()
    forms = {form for h in hashes for form in (h.lower(), h.upper())}
    return {row[0].lower() for row in session.query(ClientTorrent.info_hash)
            .filter(ClientTorrent.info_hash.in_(forms)).distinct()}


def _status_for(session: Session, candidate: Candidate) -> str:
    """auto_approved ("consigliata") sopra la soglia della sua direzione, pending sotto."""
    return "auto_approved" if candidate.confidence >= get_confidence_threshold(session, candidate.direction) \
        else "pending"


def _files_mapping(candidate: Candidate) -> frozenset[tuple]:
    return frozenset((f.torrent_path, f.size_bytes, f.media_file_id, f.seed_file_id) for f in candidate.files)


def _same_when_known(a: str | None, b: str | None) -> bool:
    return a is None or b is None or a.lower() == b.lower()


def _same_proposal(review: MatchReview, pick: Candidate, status: str) -> bool:
    """La review in coda propone già questo torrent, nello stesso formato e
    con lo stesso esito, e la nuova valutazione lo ricrea allo stesso modo:
    gli stessi file del torrent sugli stessi file locali, e lo stesso info
    hash e la stessa cartella quando entrambe le valutazioni li conoscono.
    Allora la nuova ricerca la conferma; con un abbinamento diverso no, la
    review deve puntare alla valutazione nuova (audit 2026-10-18: il
    controllo completo e l'esecuzione usavano quella vecchia)."""
    current = review.candidate
    return (current is not None and review.status == status
            and (current.tracker_id, current.torrent_id_remote, current.direction)
            == (pick.tracker_id, pick.torrent_id_remote, pick.direction)
            and candidate_format(current) == candidate_format(pick)
            and _files_mapping(current) == _files_mapping(pick)
            and _same_when_known(current.info_hash, pick.info_hash)
            and _same_when_known(current.folder, pick.folder))


class CatalogSearch(NamedTuple):
    """La ricerca sul catalogo appena fatta per un file: il tracker e gli id
    di tutti i torrent che ha restituito, anche quelli scartati prima di
    valutarli (il singolo di un altro episodio, un pack che un altro
    episodio ha già valutato in questa run, uno già visto dalla history)."""

    tracker_id: int
    returned: frozenset[str]


class _Exclusions:
    """I torrent che non si possono proporre per un file: rifiutati
    dall'utente per quel file (anche come pack di un altro episodio, lo
    stesso "no" per tutta la stagione), già in coda o in esecuzione per un
    altro file, già in un client, o un upload di Nazgarr non ancora
    indicizzato."""

    def __init__(self, session: Session, *, media_file_id: int | None, seed_file_id: int | None,
                 in_client: set[str] | None, queue: ReviewQueue | None):
        self.rejected = _user_rejected_torrents(session, media_file_id=media_file_id, seed_file_id=seed_file_id)
        if queue is not None:
            in_client = queue.in_client
            self.busy = queue.busy_for(media_file_id, seed_file_id)
            uploaded, uploaded_hashes = queue.uploaded, queue.uploaded_hashes
        else:
            in_client = hashes_in_clients(session) if in_client is None else in_client
            self.busy = _torrents_already_in_progress(
                session, media_file_id=media_file_id, seed_file_id=seed_file_id, in_client=in_client)
            uploaded, uploaded_hashes = _own_uploads(session)
        self.refused = self.rejected | uploaded
        self.hashes = in_client | uploaded_hashes

    def impossible(self, candidate: Candidate) -> bool:
        """Mai eseguibile per questo file: il client rifiuterebbe un torrent
        che ha già (con un'altra copia dei file), un upload di Nazgarr è già
        in seed, e un "no" dell'utente resta."""
        return ((candidate.tracker_id, candidate.torrent_id_remote) in self.refused
                or (bool(candidate.info_hash) and candidate.info_hash.lower() in self.hashes))

    def allows(self, candidate: Candidate) -> bool:
        return (not self.impossible(candidate)
                and (candidate.tracker_id, candidate.torrent_id_remote) not in self.busy)

    def follow(self, queue: ReviewQueue) -> None:
        """Gli upload e gli info hash appena riletti dalla coda (refresh_uploads)."""
        self.refused = self.rejected | queue.uploaded
        self.hashes = queue.in_client | queue.uploaded_hashes


def _drop_unavailable(
    session: Session, *, media_file_id: int | None, seed_file_id: int | None, tracker_id: int,
    formats: frozenset[str], queue: ReviewQueue | None, exclusions: _Exclusions | None = None,
    returned: frozenset[str] | None = None, evaluated: list[Candidate] | None = None,
    in_client: set[str] | None = None,
) -> int:
    """Una ricerca che non lascia nessuna proposta nuova: delle review in
    coda per il file su questo tracker restano solo quelle che si possono
    ancora eseguire. Escono quelle su un torrent ora impossibile
    (_Exclusions.impossible), su uno che la ricerca sul catalogo non
    restituisce più (returned, se il catalogo è stato cercato) e su uno che
    la nuova valutazione dà per non plausibile (evaluated). Resta quella su un
    torrent ora occupato da un altro file, o su un pack che un altro episodio
    ha già valutato in questa run."""
    if queue is not None and not queue.has_reviews(tracker_id, media_file_id, seed_file_id):
        return 0  # quasi sempre: niente da leggere
    active = _active_reviews(session, media_file_id=media_file_id, seed_file_id=seed_file_id,
                             tracker_id=tracker_id, formats=formats)
    if not active:
        return 0
    if exclusions is None:
        exclusions = _Exclusions(session, media_file_id=media_file_id, seed_file_id=seed_file_id,
                                 in_client=in_client, queue=queue)
    evaluated = evaluated or []
    implausible = ({c.torrent_id_remote for c in evaluated}
                   - {c.torrent_id_remote for c in evaluated if c.confidence > 0.0})
    gone = [
        r for r in active
        if exclusions.impossible(r.candidate) or r.candidate.torrent_id_remote in implausible
        or (returned is not None and r.candidate.torrent_id_remote not in returned)
    ]
    return _reject_by_system(session, gone, queue)


def _create_review(
    session: Session, candidates: list[Candidate], *, media_file_id: int | None, seed_file_id: int | None,
    in_client: set[str] | None = None, formats: frozenset[str] = FORMATS, both_formats: bool = False,
    prefer_pack: bool = False, queue: ReviewQueue | None = None, searched: CatalogSearch | None = None,
) -> MatchReview | None:
    """in_client: gli info hash nei client, se il chiamante li ha già letti;
    queue: la coda del passaggio di matching (ReviewQueue), che li ha già
    letti insieme ai torrent occupati, una volta per tracker invece che per
    ogni file. formats: quelli cercati per il file. Solo per un episodio:
    both_formats ("pack e singoli dello stesso tracker") fa una review per
    formato, prefer_pack una sola, col pack se ce n'è uno plausibile.
    searched: la ricerca sul catalogo appena fatta (CatalogSearch), None se
    il catalogo non è stato cercato (solo la history). Restituisce la prima
    review (il pack, se c'è).

    Una review già in coda che propone lo stesso torrent con lo stesso esito
    resta com'è, invece di essere rifiutata dal sistema e rifatta uguale a
    ogni nuova ricerca (audit 2026-10-18): niente eventi review.decided e
    review.created ogni settimana per la stessa proposta, e restano la
    categoria e i tag scelti a mano e una verifica in corso."""
    returned = None
    if searched is not None:
        returned = searched.returned | {c.torrent_id_remote for c in candidates}
    if not candidates:
        # Il caso più comune nel matching. Una ricerca sul catalogo che ha
        # scartato tutto prima di valutarlo (es. i singoli degli altri
        # episodi) toglie comunque la review in coda su un torrent che il
        # tracker non restituisce più: prima restava in coda per sempre.
        if searched is not None:
            _drop_unavailable(session, media_file_id=media_file_id, seed_file_id=seed_file_id,
                              tracker_id=searched.tracker_id, formats=formats, queue=queue, returned=returned,
                              in_client=in_client)
        return None
    tracker_id = candidates[0].tracker_id  # tutti dallo stesso tracker
    plausible = [c for c in candidates if c.confidence > 0.0]
    if not plausible:
        # Nessuna proposta: quella in coda di prima per questo file non vale
        # più. Senza le query di rifiuti e torrent occupati, che servono solo
        # a scegliere fra candidati plausibili (audit 2026-10-18).
        _supersede_active_reviews(session, media_file_id=media_file_id, seed_file_id=seed_file_id,
                                  tracker_id=tracker_id, formats=formats, queue=queue)
        return None
    exclusions = _Exclusions(session, media_file_id=media_file_id, seed_file_id=seed_file_id,
                             in_client=in_client, queue=queue)
    plausible = [c for c in plausible if exclusions.allows(c)]
    if plausible and queue is not None:
        # La coda è del passaggio, letta al suo inizio: un upload pubblicato e
        # messo in seed nel frattempo si vede solo rileggendo, adesso.
        queue.refresh_uploads(session, plausible)
        exclusions.follow(queue)
        plausible = [c for c in plausible if exclusions.allows(c)]
    if not plausible:
        _drop_unavailable(session, media_file_id=media_file_id, seed_file_id=seed_file_id, tracker_id=tracker_id,
                          formats=formats, queue=queue, exclusions=exclusions, returned=returned,
                          evaluated=candidates)
        return None
    if prefer_pack and _covered_by_pack(session, media_file_id, tracker_id):
        plausible = [c for c in plausible if candidate_format(c) == PACK]
        if not plausible:
            _supersede_active_reviews(session, media_file_id=media_file_id, seed_file_id=seed_file_id,
                                      tracker_id=tracker_id, formats=formats, queue=queue)
            return None
    packs = [c for c in plausible if candidate_format(c) == PACK]
    if both_formats:
        singles = [c for c in plausible if candidate_format(c) == SINGLE]
        picks = [max(group, key=lambda c: c.confidence) for group in (packs, singles) if group]
    elif prefer_pack:
        picks = [max(packs or plausible, key=lambda c: c.confidence)]
    else:
        picks = [max(plausible, key=lambda c: c.confidence)]

    active = _active_reviews(session, media_file_id=media_file_id, seed_file_id=seed_file_id,
                             tracker_id=tracker_id, formats=formats)
    reviews, kept, created = [], [], []
    for best in picks:
        status = _status_for(session, best)
        same = next((r for r in active if r not in kept and _same_proposal(r, best, status)), None)
        if same is not None:
            kept.append(same)
            reviews.append(same)
            continue
        review = MatchReview(candidate_id=best.id, media_file_id=media_file_id, seed_file_id=seed_file_id,
                             status=status)
        if status == "auto_approved":
            review.decided_by, review.decided_at = "system", datetime.now(UTC)
        session.add(review)
        reviews.append(review)
        created.append((review, best))
    _reject_by_system(session, [r for r in active if r not in kept], queue)
    session.commit()
    if queue is not None:
        for review, best in created:
            queue.opened(review, best)
    if prefer_pack and candidate_format(picks[0]) == PACK:
        _supersede_singles_in_pack(session, picks[0], queue)
    return reviews[0]


def create_review_for_media_file(
    session: Session, media_file: MediaFile, candidates: list[Candidate], in_client: set[str] | None = None,
    formats: frozenset[str] = FORMATS, both_formats: bool = False, queue: ReviewQueue | None = None,
    searched: CatalogSearch | None = None,
) -> MatchReview | None:
    # Un film con dei contenuti extra in video non è un pack: formati solo per gli episodi.
    episode = is_episode(media_file.media_item)
    return _create_review(session, candidates, media_file_id=media_file.id, seed_file_id=None, in_client=in_client,
                          formats=formats, both_formats=both_formats and episode,
                          prefer_pack=episode and not both_formats, queue=queue, searched=searched)


def create_review_for_seed_file(
    session: Session, seed_file: SeedFile, candidates: list[Candidate], in_client: set[str] | None = None,
    queue: ReviewQueue | None = None, searched: CatalogSearch | None = None,
) -> MatchReview | None:
    return _create_review(session, candidates, media_file_id=None, seed_file_id=seed_file.id, in_client=in_client,
                          queue=queue, searched=searched)


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
    """Il controllo completo di questa review è già in corso: l'API lo dice
    col codice review_already_verifying (prima un testo libero)."""

    def __init__(self, review_id: int):
        self.review_id = review_id
        super().__init__(f"Review {review_id} is already being verified")


class ReviewAlreadyDecidedError(Exception):
    """La review non è più in coda (approvata, rifiutata dall'utente o dal
    sistema) o il suo candidato ha già un'esecuzione: niente da decidere."""

    def __init__(self, review_id: int):
        self.review_id = review_id
        super().__init__(f"Review {review_id} has already been decided")


def ready_for_decision(session: Session, review: MatchReview) -> bool:
    """La stessa regola della coda (list_ready_for_review), letta ora dal DB."""
    return without_seed_job(session.query(MatchReview.id).filter(
        MatchReview.id == review.id, MatchReview.status.in_(READY_FOR_DECISION_STATUSES))).first() is not None


def _claim(session: Session, review: MatchReview, status: str, decided_by: str) -> bool:
    """La decisione su una review, presa una volta sola (audit 2026-10-18):
    un UPDATE condizionato (ancora in coda, senza esecuzioni) apre la
    transazione di scrittura, e nella stessa transazione la review cambia
    stato. Due approvazioni insieme (un doppio clic, "Approva tutti" mentre
    una riga è ancora in corso, l'esecuzione automatica della run e quella
    dell'utente) non eseguono mai due volte, e una review chiusa dal sistema
    o già eseguita non riparte. Lo stato si scrive con l'ORM, così l'evento
    review.decided parte come sempre."""
    now = datetime.now(UTC)
    claimed = session.query(MatchReview).filter(
        MatchReview.id == review.id, MatchReview.status.in_(READY_FOR_DECISION_STATUSES),
        ~exists().where(SeedJob.candidate_id == MatchReview.candidate_id),
    ).update({MatchReview.decided_at: now}, synchronize_session=False)
    if claimed != 1:
        session.rollback()
        return False
    review.status, review.decided_by, review.decided_at = status, decided_by, now
    session.commit()
    return True


def request_approval(session: Session, review: MatchReview, session_factory, decided_by: str = "user",
                     fetch_torrent=None) -> MatchReview:
    """Approve dall'interfaccia. Con la verifica attiva la review resta in
    coda come "verifying" e parte il controllo completo in background:
    l'approvazione e l'esecuzione arrivano solo se passa (_after_verification).
    Senza verifica, come sempre: approva ed esegue subito. Una review che
    non è più in coda: ReviewAlreadyDecidedError, prima di qualunque
    controllo o esecuzione."""
    if not verify_before_execute_enabled(session):
        return approve(session, review, decided_by=decided_by)
    if review.verify_status == "verifying":
        raise AlreadyVerifyingError(review.id)
    if not ready_for_decision(session, review):
        raise ReviewAlreadyDecidedError(review.id)

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
    try:
        approve(session, review, decided_by=decided_by, skip_recheck=skip)
    except ReviewAlreadyDecidedError:
        # Decisa da un'altra parte mentre il controllo girava (la run
        # l'ha eseguita, o chiusa): questa non esegue niente.
        state.execution = "skipped"
        return
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
    non c'è più. La review torna in coda com'era, da approvare di nuovo.
    Insieme, le esecuzioni rimaste a metà (close_interrupted_seed_jobs)."""
    rows = session.query(MatchReview).filter(MatchReview.verify_status == "verifying").all()
    for row in rows:
        row.verify_status, row.verify_detail, row.verify_check_id = None, None, None
    if rows:
        session.commit()
    close_interrupted_seed_jobs(session)
    return len(rows)


INTERRUPTED_SEED_JOB = ("Interrupted by a restart while it was being added to the client: retry it "
                        "(it follows the torrent if the client got it), or delete it")


def close_interrupted_seed_jobs(session: Session) -> int:
    """All'avvio nessuna esecuzione è in corso: un seed_job "in_progress"
    senza info_hash è stato interrotto (un riavvio o un crash) fra la sua
    creazione e la risposta del client. Nessuno lo riprendeva mai: il
    controllo dei recheck guarda solo quelli con un info_hash e il retry
    solo i falliti, e il torrent restava "occupato" per sempre (audit
    2026-10-18). Diventa fallito, così si ritenta (il retry segue il
    torrent se il client l'aveva ricevuto) o si elimina. Niente cambia nel
    client o sui file."""
    rows = session.query(SeedJob).filter(SeedJob.final_status == "in_progress", SeedJob.info_hash.is_(None)).all()
    for row in rows:
        row.final_status, row.error_message = "failed", INTERRUPTED_SEED_JOB
    if rows:
        session.commit()
        logger.warning("%d esecuzioni interrotte da un riavvio segnate come fallite", len(rows))
    return len(rows)


def approve(
    session: Session, review: MatchReview, decided_by: str = "user", skip_recheck: bool = False,
) -> MatchReview:
    """Approva e prova subito l'esecuzione (hardlink+seed, o solo add al
    client) se un client torrent è configurato. Un fallimento
    dell'esecuzione non annulla l'approvazione: resta approved con il
    seed_job in stato failed — ritenta da list_failed_seed_jobs(). Solo una
    review ancora in coda, presa in modo atomico (_claim):
    ReviewAlreadyDecidedError altrimenti."""
    if not _claim(session, review, "approved", decided_by):
        raise ReviewAlreadyDecidedError(review.id)
    if skip_recheck:
        _try_execute(session, review, skip_recheck=True)
    else:
        _try_execute(session, review)
    return review


def reject(session: Session, review: MatchReview, decided_by: str = "user") -> MatchReview:
    """Come approve: solo una review ancora in coda. Prima un rifiuto poteva
    trasformare in "no dell'utente" una review già eseguita."""
    if not _claim(session, review, "rejected", decided_by):
        raise ReviewAlreadyDecidedError(review.id)
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
        # La lista si legge una volta, e un controllo completo dura minuti:
        # l'utente può averla approvata o rifiutata nel frattempo.
        if not ready_for_decision(session, review):
            progress.advance()
            continue
        verified = _verify_now(session, review, progress) if verify else None
        if verify and not verified:
            progress.advance()
            continue
        skip = verified is not None and skip_recheck_enabled(session) and fully_verified(verified, review.candidate)
        try:
            approve(session, review, decided_by="system", skip_recheck=skip)
        except ReviewAlreadyDecidedError:
            progress.advance()
            continue
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


def with_details(query):
    """Le review con quello che la coda ne mostra (candidato, contenuto,
    tracker, file del torrent coi file locali) caricato in blocco, non con
    una query per review e per file (audit 2026-10-18)."""
    candidate = selectinload(MatchReview.candidate)
    return query.options(
        candidate.selectinload(Candidate.files).joinedload(CandidateFile.media_file),
        candidate.selectinload(Candidate.files).joinedload(CandidateFile.seed_file),
        candidate.joinedload(Candidate.media_item),
        candidate.joinedload(Candidate.tracker),
    )


def list_ready_for_review(session: Session) -> list[MatchReview]:
    """match_review in attesa di una decisione (pending o auto_approved) il
    cui candidate non ha ancora un seed_job — esclude quelle già eseguite
    (con successo o meno) in un tentativo precedente."""
    return without_seed_job(
        session.query(MatchReview).filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES))).all()


def queue_groups(session: Session) -> list[list[int]]:
    """Gli id delle review in coda, nell'ordine della coda e a gruppi come li
    mostra la pagina Reseeding (frontend/src/lib/reviewGroups.ts): gli
    episodi singoli della stessa stagione, dello stesso tracker e direzione,
    insieme, in ordine di episodio; ogni altra review da sola. I gruppi
    nell'ordine della loro prima review. Una query leggera per tutta la
    coda: le pagine si tagliano fra un gruppo e l'altro, mai dentro."""
    videos = (
        select(func.count(CandidateFile.id))
        .where(CandidateFile.candidate_id == Candidate.id, CandidateFile.is_video.is_(True))
        .scalar_subquery()
    )
    rows = without_seed_job(
        session.query(MatchReview.id, Candidate.direction, Candidate.tracker_id, MediaItem.tmdb_id,
                      MediaItem.season_number, MediaItem.episode_number, videos)
        .join(Candidate, Candidate.id == MatchReview.candidate_id)
        .outerjoin(MediaItem, MediaItem.id == Candidate.media_item_id)
        .filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES))
    ).order_by(MatchReview.id).all()
    seasons: dict[tuple, list[tuple[int, int]]] = {}
    groups: list[list[tuple[int, int]]] = []
    for review_id, direction, tracker_id, tmdb_id, season, episode, video_count in rows:
        single_episode = (torrent_format(video_count or 0) == SINGLE and tmdb_id is not None
                          and season is not None and episode is not None)
        key = (direction, tracker_id, tmdb_id, season) if single_episode else None
        if key is not None and key in seasons:
            seasons[key].append((episode, review_id))
            continue
        group = [(episode or 0, review_id)]
        if key is not None:
            seasons[key] = group
        groups.append(group)
    return [[review_id for _episode, review_id in sorted(group, key=lambda e: e[0])] for group in groups]


def one_per_torrent(session: Session, media_item_ids: list[int], *, limit: int, newest: bool,
                    by_direction: bool) -> list[Candidate]:
    """I candidati valutati per questi contenuti, uno per torrent (tracker e
    id sul tracker, e direzione se by_direction): il più recente (newest) o
    quello a confidence più alta, poi i migliori fino a limit. Scelti in SQL:
    prima si caricavano tutti, con i loro file, e si tagliava dopo (audit
    2026-10-18)."""
    if not media_item_ids:
        return []
    partition = [Candidate.tracker_id, Candidate.torrent_id_remote] + ([Candidate.direction] if by_direction else [])
    order = [Candidate.id.desc()] if newest else [Candidate.confidence.desc(), Candidate.id.desc()]
    ranked = (
        select(Candidate.id.label("id"),
               func.row_number().over(partition_by=partition, order_by=order).label("position"))
        .where(Candidate.media_item_id.in_(media_item_ids))
        .subquery()
    )
    return (
        session.query(Candidate)
        .join(ranked, ranked.c.id == Candidate.id)
        .filter(ranked.c.position == 1)
        .options(selectinload(Candidate.files).joinedload(CandidateFile.media_file),
                 selectinload(Candidate.files).joinedload(CandidateFile.seed_file))
        .order_by(Candidate.confidence.desc(), Candidate.id.desc())
        .limit(limit)
        .all()
    )


def load_reviews(session: Session, review_ids: list[int]) -> list[MatchReview]:
    """Quelle review, con with_details, nell'ordine dato."""
    if not review_ids:
        return []
    by_id = {r.id: r for r in with_details(session.query(MatchReview).filter(MatchReview.id.in_(review_ids)))}
    return [by_id[i] for i in review_ids if i in by_id]


def count_ready_for_review(session: Session) -> int:
    """Quante sono, contate in SQL."""
    return without_seed_job(
        session.query(MatchReview.id).filter(MatchReview.status.in_(READY_FOR_DECISION_STATUSES))).count()


def list_failed_seed_jobs(session: Session) -> list[SeedJob]:
    return session.query(SeedJob).filter_by(final_status="failed").all()


# Le esecuzioni che si possono eliminare: una in seed resta, è il record
# di cosa Nazgarr ha aggiunto al client.
DELETABLE_SEED_JOB_STATUSES = ("failed", "in_progress")


class SeedJobNotDeletable(CodedError, ExecutionError):
    """Un'esecuzione in seed (o in un altro stato finale che non è un
    fallimento) non si elimina: l'API lo dice col codice
    seed_job_not_deletable (audit 2026-10-18, prima un testo libero).
    Resta un ExecutionError per chi lo chiama da Python."""

    def __init__(self, seed_job: SeedJob):
        super().__init__("seed_job_not_deletable", id=seed_job.id, status=seed_job.final_status)


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
        raise SeedJobNotDeletable(seed_job)
    candidate = session.get(Candidate, seed_job.candidate_id)
    file_filter = (
        {"media_file_id": seed_job.source_media_file_id} if seed_job.source_media_file_id is not None
        else {"seed_file_id": seed_job.source_seed_file_id}
    )
    for row in (
        session.query(MatchReview).filter_by(candidate_id=seed_job.candidate_id, **file_filter)
        .filter(MatchReview.status.in_((*READY_FOR_DECISION_STATUSES, "approved")))
    ):
        row.status, row.decided_by, row.decided_at = "rejected", "system", datetime.now(UTC)
    if candidate is not None:
        session.query(MatchAttempt).filter_by(tracker_id=candidate.tracker_id, **file_filter).delete()
    logger.info("Seed job %s (%s) eliminato su richiesta", seed_job.id, seed_job.final_status)
    seen_in_client(seed_job.id)
    session.delete(seed_job)
    session.commit()


def _client_for_seed_job(session: Session, seed_job: SeedJob):
    # Col client dove era stato aggiunto, se si sa; altrimenti quello del tracker.
    return (
        _client_for(session, seed_job.torrent_client_id)
        if seed_job.torrent_client_id is not None
        else _client_for_candidate(session, seed_job.candidate)
    )


def _retried_already(session: Session, seed_job: SeedJob) -> bool:
    """Il candidato ha già un'esecuzione più recente: questa è già stata ritentata."""
    return session.query(SeedJob.id).filter(
        SeedJob.candidate_id == seed_job.candidate_id, SeedJob.id > seed_job.id).first() is not None


def retry_failed(session: Session, seed_job: SeedJob, session_factory=None):
    """Ritenta un'esecuzione fallita. Se il client ha già il torrent lo si
    segue, come sempre (nessun file creato, nessun torrent aggiunto). Da
    zero, con il controllo completo prima di eseguire acceso (il default) e
    session_factory: parte quel controllo, come per un'approvazione, e
    l'esecuzione arriva solo se passa (audit 2026-10-18: il retry
    rieseguiva senza, anche se i file erano cambiati dall'ultima volta).
    Restituisce il seed_job, o lo stato del controllo partito
    (full_check.CheckState). Un retry che non si fa: RetryRefused, col suo
    codice (non fallito, già ritentato, nessun client, il torrent nel
    client non è di questa esecuzione)."""
    if seed_job.final_status != "failed":
        raise RetryRefused("seed_job_not_failed", id=seed_job.id, status=seed_job.final_status)
    if _retried_already(session, seed_job):
        raise RetryRefused("seed_job_already_retried", id=seed_job.id)
    adapter, torrent_client_id = _client_for_seed_job(session, seed_job)
    if adapter is None:
        raise RetryRefused("seed_job_no_client")
    try:
        adopted = adopt_for_retry(session, seed_job, adapter)
        if adopted is not None:
            return adopted
        if session_factory is not None and verify_before_execute_enabled(session):
            return _verify_then_retry(session, seed_job, session_factory)
        return retry_from_scratch(session, seed_job, adapter, torrent_client_id)
    finally:
        close_adapter(adapter)


def _verify_then_retry(session: Session, seed_job: SeedJob, session_factory):
    match_review = review_of(session, seed_job)
    seed_job_id = seed_job.id

    def after(worker_session: Session, state, result) -> None:
        _after_retry_verification(worker_session, state, result, seed_job_id)

    return full_check.start_check(
        session_factory, session, seed_job.candidate_id, media_file_id=match_review.media_file_id,
        purpose="verify", review_id=match_review.id, after=after,
    )


def _after_retry_verification(session: Session, state, result, seed_job_id: int) -> None:
    """Nel worker del controllo: il retry da zero solo se il controllo è
    passato e nessun'altra esecuzione l'ha già rifatto nel frattempo."""
    seed_job = session.get(SeedJob, seed_job_id)
    if (result is None or state.verdict != "passed" or seed_job is None or seed_job.final_status != "failed"
            or _retried_already(session, seed_job)):
        state.execution = "skipped"
        return
    state.stage = "executing"
    adapter, torrent_client_id = _client_for_seed_job(session, seed_job)
    if adapter is None:
        state.execution = "no_client"
        return
    try:
        skip = skip_recheck_enabled(session) and fully_verified(result, seed_job.candidate)
        again = retry_from_scratch(session, seed_job, adapter, torrent_client_id, skip_recheck=skip)
        state.execution = "failed" if again.final_status == "failed" else "added"
        state.execution_error = again.error_message if again.final_status == "failed" else None
    except ExecutionError as exc:
        state.execution, state.execution_error = "failed", safe_error(exc)
    finally:
        close_adapter(adapter)


def reconcile_pending_seed_jobs(session: Session, progress=NULL_PROGRESS) -> dict[str, int]:
    """Ricontrolla lo stato reale nel client per ogni seed_job ancora
    'in_progress' con un info_hash già noto — una sola interrogazione di
    stato per client (mai un hardlink o un add_torrent), quindi non viola
    la regola "nessuna esecuzione senza conferma umana": al più avvia un
    reseed approvato il cui recheck è riuscito (entra fermo, decisione
    dell'utente del 2026-10-18) e ferma uno fallito che gira. Un seed appena
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
    broken: set[int | None] = set()
    try:
        for seed_job in pending:
            progress.advance()
            if seed_job.torrent_client_id is not None and not _client_enabled(session, seed_job.torrent_client_id):
                # Il primo client abilitato non ha quel torrent: chiederlo a
                # lui dava un errore a ogni giro, per sempre.
                _give_up(session, seed_job, "The client it was added to is disabled or deleted: "
                                            "enable it again, then retry")
                continue
            key = (seed_job.torrent_client_id if seed_job.torrent_client_id is not None
                   else -seed_job.candidate.tracker_id)
            if key not in adapters:
                try:
                    adapters[key] = (
                        _client_for(session, seed_job.torrent_client_id)
                        if seed_job.torrent_client_id is not None
                        else _client_for_candidate(session, seed_job.candidate)
                    )
                except Exception:
                    # Un client che non si costruisce (il suo host ora risolve
                    # a una destinazione vietata, net_guard) fermava il giro
                    # intero: nessun reseed degli altri client si avviava più.
                    logger.exception("Client del seed_job %s non costruito: i suoi reseed restano in corso",
                                     seed_job.id)
                    adapters[key] = (None, None)
                    broken.add(key)
            adapter, torrent_client_id = adapters[key]
            if adapter is None:
                if key in broken:
                    errors += 1
                continue
            try:
                reconcile_seed_job(session, seed_job, adapter)
                reconciled += 1
                seen_in_client(seed_job.id)
                _failing.discard(seed_job.id)
            except Exception as exc:
                session.rollback()
                found = lookup_torrent(adapter, seed_job.info_hash)
                if found == "missing":
                    # 10 minuti di fila (executor.missing_long_enough), non
                    # dall'aggiunta: un client riavviato che ricarica ancora
                    # i suoi torrent non fa fallire un reseed in corso da ore.
                    if missing_long_enough(seed_job):
                        _give_up(session, seed_job, GONE_FROM_CLIENT)
                    else:
                        logger.info("Seed_job %s: torrent non (ancora) nel client, riprovo dopo", seed_job.id)
                    continue
                if seed_job.id in _failing:
                    # La traccia è già nel log: ogni 2 minuti, per sempre (un
                    # plugin che non sa dire se il torrent c'è), una riga.
                    logger.warning("Reconcile ancora fallito per seed_job %s: %s", seed_job.id, safe_error(exc))
                else:
                    _failing.add(seed_job.id)
                    logger.exception("Reconcile fallito per seed_job %s", seed_job.id)
                errors += 1
                if found == "unreachable":
                    # Il client non ha risposto a nessuna delle due domande:
                    # gli altri suoi job saltano questo giro (contati come
                    # errori). Il giro è lavoro a lato e tiene il lock delle
                    # run (scheduler._reconcile_between_runs): con un client
                    # che non risponde ogni job costava due timeout, minuti
                    # di webhook, "Cerca ora" e run fermi (revisione
                    # dell'audit 2026-10-18). Un adapter che non sa cercare
                    # un torrent solo ("unknown", un plugin) va avanti: un
                    # torrent sbagliato non ferma gli altri.
                    logger.warning("Il client del seed_job %s non risponde: i suoi reseed si ricontrollano al "
                                   "prossimo giro", seed_job.id)
                    close_adapter(adapter)
                    adapters[key] = (None, None)
                    broken.add(key)
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


# I seed job il cui reconcile è fallito con un errore che non dice "il
# torrent non c'è" (il client non risponde, un plugin senza get_torrent_info):
# la traccia la prima volta, poi una riga (audit 2026-10-18, finding 113).
_failing: set[int] = set()


def _client_enabled(session: Session, torrent_client_id: int) -> bool:
    row = session.get(TorrentClient, torrent_client_id)
    return row is not None and bool(row.enabled)


GONE_FROM_CLIENT = "The torrent is no longer in the client: retry it to add it again, or delete it"


def _give_up(session: Session, seed_job: SeedJob, message: str) -> None:
    """Un'esecuzione che non arriverà mai a un esito: fallita, con il
    perché, così si ritenta o si elimina dalla pagina Reseeding."""
    seed_job.final_status, seed_job.error_message = "failed", message
    session.commit()
    seen_in_client(seed_job.id)
    _failing.discard(seed_job.id)
    logger.warning("Seed_job %s: %s", seed_job.id, message)


def has_pending_seed_jobs(session: Session) -> bool:
    return (
        session.query(SeedJob.id)
        .filter(SeedJob.final_status == "in_progress", SeedJob.info_hash.isnot(None))
        .first()
        is not None
    )
