"""Passo 'identifying' del flusso di upload v2 (docs/SPEC.md §9): cosa c'è
nella sorgente (nazgarr/upload/source.py) e con quale contenuto TMDB combacia.
Porta il job al primo punto di approvazione, awaiting_match, con una lista
di candidati ordinata: il primo è quello suggerito.

Da dove vengono i candidati, in ordine:
1. gli id forzati dall'utente (TMDB diretto, IMDB/TVDB via /find): se ci
   sono, sono gli unici candidati, l'utente ha già detto cosa vuole;
2. il resolver della libreria (Radarr/Sonarr se configurati, poi guessit +
   TMDB), lo stesso che identifica i file durante lo scan;
3. la ricerca TMDB per titolo (e anno) letti dal nome della sorgente, nel
   tipo rilevato e, con pochi risultati, anche nell'altro: guessit a volte
   scambia una serie per un film.

Nessun candidato non è un errore: dalla schermata di match l'utente può
cercare a mano o forzare un id.
"""

import json
import logging
import re
from dataclasses import asdict

import httpx
from sqlalchemy import delete
from sqlalchemy.orm import Session

from nazgarr.core import settings_registry, settings_repo
from nazgarr.core.models import UploadJob
from nazgarr.integrations import adapter_factory
from nazgarr.integrations.adapter_factory import TmdbApiKeyMissingError
from nazgarr.library import episode_orders
from nazgarr.library.tmdb_client import TMDBClient
from nazgarr.upload import analysis as upload_analysis
from nazgarr.upload import jobs as upload_jobs
from nazgarr.upload import match_score as upload_match_score
from nazgarr.upload import pack as upload_pack
from nazgarr.upload import split as upload_split
from nazgarr.upload.source import SourceLayout, scan_source

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 8
# Lo stage di un job della cartella osservata confermato e non ancora
# guardato dalla divisione (nazgarr/upload/split.py): scritto con il match,
# tolto quando la divisione ha deciso. Se resta, un riavvio l'ha fermata a
# metà, e l'analisi la rifà (resume_split).
SPLIT_PENDING = "split_pending"
# Gli stati di un upload creato da una divisione che non ha ancora fatto
# niente fuori da Nazgarr (né analisi finita, né decisione).
_UNSTARTED = ("identifying", "awaiting_match", "analyzing")
# Sotto questo numero di risultati nel tipo rilevato si cerca anche nell'altro.
_OTHER_TYPE_THRESHOLD = 3

_TMDB_REF = re.compile(r"(?:(movie|tv)[/:])?(\d+)(?:[-/?#].*)?$")


def tmdb_client(session: Session) -> TMDBClient:
    api_key = settings_repo.get_setting(session, "tmdb_api_key")
    if not api_key:
        raise TmdbApiKeyMissingError("tmdb_api_key_missing")
    return TMDBClient(api_key=api_key)


def parse_tmdb_ref(value: str, default_type: str) -> tuple[str, int] | None:
    """"603", "movie/603", "tv/1399" o un URL themoviedb.org -> (tipo, id)."""
    text = str(value).strip().rstrip("/")
    text = re.sub(r"^https?://(www\.)?themoviedb\.org/", "", text)
    match = _TMDB_REF.match(text)
    if match is None:
        return None
    return (match.group(1) or default_type), int(match.group(2))


def normalize_imdb(value: str) -> str | None:
    match = re.search(r"(?:tt)?(\d{5,})", str(value))
    return f"tt{match.group(1)}" if match else None


def _add(candidates: list[dict], new: list[dict], source: str) -> None:
    by_key = {(c["content_type"], c["tmdb_id"]): c for c in candidates}
    for candidate in new:
        key = (candidate["content_type"], candidate["tmdb_id"])
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = {**candidate, "source": candidate.get("source") or source}
            candidates.append(by_key[key])
            continue
        # Lo stesso contenuto, già trovato (es. dal resolver): i suoi titoli in
        # altre lingue servono comunque al confronto del nome (upload_match_score).
        for title in [candidate.get("title"), *(candidate.get("titles") or [])]:
            known = [existing.get("title"), existing.get("original_title"), *(existing.get("titles") or [])]
            if title and title not in known:
                existing.setdefault("titles", []).append(title)


def _forced_candidates(client: TMDBClient, forced: dict, layout: SourceLayout) -> list[dict]:
    candidates: list[dict] = []
    if forced.get("tmdb"):
        ref = parse_tmdb_ref(forced["tmdb"], layout.content_type)
        if ref is None:
            raise upload_jobs.UploadJobError("upload_invalid_tmdb_id", value=forced["tmdb"])
        content_type, tmdb_id = ref
        details = client.full_details(content_type, tmdb_id)
        _add(candidates, [details], "forced_tmdb")
    if forced.get("imdb"):
        imdb_id = normalize_imdb(forced["imdb"])
        if imdb_id is None:
            raise upload_jobs.UploadJobError("upload_invalid_imdb_id", value=forced["imdb"])
        _add(candidates, client.find("imdb", imdb_id), "forced_imdb")
    if forced.get("tvdb"):
        _add(candidates, client.find("tvdb", str(forced["tvdb"])), "forced_tvdb")
    return candidates


def _resolver_candidates(session: Session, main_video: str) -> list[dict]:
    try:
        resolver = adapter_factory.build_media_resolver(session, upload_analysis.arr_index_if_configured(session))
    except TmdbApiKeyMissingError:
        return []
    try:
        resolved = resolver.resolve(main_video)
    except Exception:
        # Il resolver è solo una delle fonti: la ricerca per titolo resta.
        logger.warning("Resolver fallito per %r", main_video, exc_info=True)
        return []
    if resolved is None:
        return []
    if resolved.content_type not in ("movie", "tv"):
        # Un resolver di un plugin con un altro tipo: un candidato così non
        # si potrebbe né confermare né mostrare (UploadCandidateResponse).
        logger.warning("Resolver: tipo %r per %r ignorato", resolved.content_type, main_video)
        return []
    return [{
        "tmdb_id": resolved.tmdb_id,
        "content_type": resolved.content_type,
        "title": resolved.title,
        "original_title": None,
        "year": resolved.year,
        "poster_path": resolved.poster_path,
        "overview": None,
        "source": resolved.source or resolver.SOURCE,
    }]


def _search_candidates(client: TMDBClient, layout: SourceLayout, languages: tuple[str, ...] = ()) -> list[dict]:
    if not layout.title:
        return []
    results = client.search_many(layout.content_type, layout.title, layout.year)
    if layout.year and not results:
        results = client.search_many(layout.content_type, layout.title)
    # Nella lingua dei tracker (es. un file con il titolo italiano): i titoli
    # tradotti per il confronto ("titles", nazgarr/upload/match_score.py), e
    # i risultati che si trovano solo così.
    by_key = {(r["content_type"], r["tmdb_id"]): r for r in results}
    for language in languages:
        localized = client.search_many(layout.content_type, layout.title, layout.year, language=language)
        if layout.year and not localized:
            localized = client.search_many(layout.content_type, layout.title, language=language)
        for result in localized:
            key = (result["content_type"], result["tmdb_id"])
            if key in by_key:
                by_key[key].setdefault("titles", [])
                if result.get("title"):
                    by_key[key]["titles"].append(result["title"])
            else:
                result["titles"] = [result["title"]] if result.get("title") else []
                by_key[key] = result
                results.append(result)
    # Prima quelli usciti proprio nell'anno del nome, poi l'ordine di TMDB.
    if layout.year:
        results.sort(key=lambda r: r["year"] != layout.year)
    if len(results) < _OTHER_TYPE_THRESHOLD:
        other = "movie" if layout.content_type == "tv" else "tv"
        results += client.search_many(other, layout.title, layout.year)[:2]
    return results


def find_candidates(
    session: Session, forced: dict, layout: SourceLayout, languages: tuple[str, ...] = ()
) -> list[dict]:
    try:
        client = tmdb_client(session)
    except TmdbApiKeyMissingError:
        client = None
    if forced and client is not None:
        forced_candidates = _forced_candidates(client, forced, layout)
        if forced_candidates:
            return upload_match_score.scored(forced_candidates, layout.title, layout.year,
                                             layout.content_type)[:MAX_CANDIDATES]

    candidates: list[dict] = []
    _add(candidates, _resolver_candidates(session, layout.main_video), "resolver")
    if client is not None:
        _add(candidates, _search_candidates(client, layout, languages), "search")
    # Ognuno con la sua confidence (nazgarr/upload/match_score.py), dal più
    # sicuro. Prima il punteggio su tutti, poi i primi: tagliati prima, una
    # serie con lo stesso titolo oltre l'ottavo posto non contava né per
    # l'ambiguità né per l'anno non richiesto, e il primo passava da solo
    # (audit 2026-10-18).
    return upload_match_score.scored(candidates, layout.title, layout.year, layout.content_type)[:MAX_CANDIDATES]


AUTO_MATCH_SETTING = "upload_auto_match_threshold"


def auto_match_threshold(session: Session) -> float | None:
    """La confidence oltre la quale un upload conferma da solo il match
    (Settings > Upload). Mai salvata = 0.9; 0 = spento."""
    value = settings_registry.get_float(session, AUTO_MATCH_SETTING)
    return value if 0 < value <= 1 else None


def _auto_match(session: Session, job: UploadJob, candidates: list[dict]) -> tuple[bool, dict | None]:
    """Per ogni upload, dalla cartella osservata o creato a mano (decisione
    dell'utente, 2026-10-02): il candidato più sicuro, se supera la soglia, si
    conferma da solo, con gli stessi controlli della conferma a mano. Sotto
    soglia, se è ambiguo o se qualcosa non torna (tipo, stagione), il job
    aspetta al match come sempre. Dalla decisione si torna indietro con
    "Change match" (back_to_match). (confermato, dettagli TMDB)."""
    if not candidates:
        return False, None
    best = candidates[0]
    threshold = auto_match_threshold(session)
    if threshold is None:
        return False, None  # spento: niente da dire nel registro
    if best.get("ambiguous") or best.get("confidence", 0) < threshold:
        upload_jobs.log_event(session, job, "auto_match_skipped", confidence=best.get("confidence", 0),
                              threshold=threshold)
        session.commit()
        return False, None
    try:
        details = tmdb_client(session).full_details(best["content_type"], best["tmdb_id"])
    except TmdbApiKeyMissingError:
        details = None
    except httpx.HTTPError:
        logger.warning("Dettagli TMDB non disponibili per il match automatico del job %s", job.id, exc_info=True)
        upload_jobs.log_event(session, job, "auto_match_failed", level="warning")
        session.commit()
        return False, None
    orders = None
    if best["content_type"] == "tv":
        # L'ordinamento che combacia meglio con i file, come al match a mano;
        # se non è TVDB aired lo dice il registro.
        try:
            orders = episode_orders.for_job(session, job, best["tmdb_id"], (details or {}).get("tvdb_id"))
        except Exception:
            logger.warning("Ordinamenti degli episodi non disponibili per il job %s", job.id, exc_info=True)
    order_key = orders["recommended"] if orders else None
    # Dalla cartella osservata un pack passa poi dalla divisione: lo dice lo
    # stage scritto insieme al match, così un riavvio a metà non la salta.
    pending = job.origin == "watch" and job.kind in ("season_pack", "complete_pack") and (
        upload_split.enabled(session) or upload_split.seasons_enabled(session))
    try:
        # I numeri dei file tradotti nell'ordinamento scelto, come li manda il
        # match a mano. Una scelta automatica non diventa la preferenza della serie.
        confirm(session, job, content_type=best["content_type"], tmdb_id=best["tmdb_id"], kind=job.kind,
                seasons=json.loads(job.seasons_json or "[]"), episode=job.episode, details=details,
                order_key=order_key, orders=orders, translate=True, remember=False, split_pending=pending)
    except upload_jobs.UploadJobError as exc:
        session.rollback()
        upload_jobs.log_event(session, job, "auto_match_failed", level="warning", reason=exc.code)
        session.commit()
        return False, None
    if order_key and orders["warning"]:
        upload_jobs.log_event(session, job, "episode_order_not_tvdb_aired", level="warning",
                              order=json.loads(job.episode_order_json)["chosen"]["label"])
    upload_jobs.log_event(session, job, "auto_matched", confidence=best["confidence"], title=job.title,
                          year=job.year)
    session.commit()
    return True, details


def confirm(
    session: Session, job: UploadJob, *, content_type: str, tmdb_id: int, kind: str | None,
    seasons: list[int], episode: int | None, details: dict | None,
    order_key: str | None = None, orders: dict | None = None, translate: bool = False, remember: bool = False,
    split_pending: bool = False,
) -> None:
    """Il primo punto di approvazione, uguale dal match a mano (API) e da
    quello automatico: contenuto, stagioni ed episodio, e per le serie
    l'ordinamento degli episodi scelto (salvato sul job: nome, file e campi
    del tracker usano la sua numerazione).
    translate: seasons/episode sono nella numerazione dei file e vanno
    tradotti (auto-match); il frontend li manda già tradotti.
    remember: la scelta diventa la proposta per la serie (solo una scelta
    dell'utente). split_pending: la divisione della cartella osservata deve
    ancora guardarlo (SPLIT_PENDING, nello stesso UPDATE del match).
    episode_orders.EpisodeOrderError per un ordinamento che la serie non ha,
    UploadJobError se il match non è valido. Il commit è del chiamante."""
    snapshot = None
    if content_type == "tv" and order_key:
        orders = orders or episode_orders.for_job(session, job, tmdb_id, (details or {}).get("tvdb_id"))
        snapshot = episode_orders.snapshot(orders, order_key)
        if translate:
            seasons, episode = episode_orders.numbers_in(orders, order_key, kind, seasons, episode)
    # Solo alcune stagioni di una cartella che ne ha di più: solo i loro file.
    selection = upload_pack.season_selection(job, kind, seasons, snapshot) if content_type == "tv" else {}
    before = len(json.loads(job.layout_json or "{}").get("videos") or []) if selection else 0
    upload_jobs.confirm_match(
        session, job, content_type=content_type, tmdb_id=tmdb_id, kind=kind, seasons=seasons, episode=episode,
        details=details, forced=json.loads(job.forced_ids_json or "{}"),
        source_values={**selection, "stage": SPLIT_PENDING} if split_pending else selection,
    )
    if selection:
        videos = len(json.loads(job.layout_json or "{}").get("videos") or [])
        upload_jobs.log_event(session, job, "pack_from_seasons",
                              seasons=", ".join(f"S{s:02d}" for s in sorted(set(seasons))),
                              count=videos, left=before - videos)
    job.episode_order = order_key if snapshot is not None else None
    job.episode_order_json = json.dumps(snapshot) if snapshot is not None else None
    if snapshot is not None:
        # Episodi dei file che l'ordinamento scelto non ha: tengono i numeri
        # dei file, e la decisione lo deve dire (audit 2026-10-18).
        missing = episode_orders.untranslated(snapshot, episode_orders.found_in_layout(job.layout_json))
        if missing:
            upload_jobs.log_event(session, job, "episode_order_untranslated", level="warning",
                                  order=snapshot["chosen"]["label"], count=len(missing),
                                  episodes=", ".join(f"S{s:02d}E{e:02d}" for s, e in missing[:10]))
    if snapshot is not None and remember:
        episode_orders.remember(session, tmdb_id, order_key)


def handle(session: Session, job: UploadJob, worker) -> None:
    if drop_split_orphan(session, job):
        return
    upload_jobs.log_event(session, job, "identify_started")
    session.commit()
    try:
        if upload_pack.is_pack(job):
            layout = scan_source(job.source_path, upload_pack.entries(job), upload_pack.name(job))
        else:
            layout = scan_source(job.source_path)
    except ValueError as exc:
        raise upload_jobs.UploadJobError(str(exc)) from exc
    except OSError as exc:
        raise upload_jobs.UploadJobError("upload_source_unreadable", error=str(exc)) from exc

    forced = json.loads(job.forced_ids_json or "{}")
    # Le lingue dei tracker del job, oltre all'inglese di TMDB.
    languages = tuple(sorted({t.tracker.language for t in job.targets if t.tracker.language} - {"en"}))
    candidates = find_candidates(session, forced, layout, languages)
    if not record_identification(session, job, layout, candidates):
        return
    confirmed, details = _auto_match(session, job, candidates)
    if not confirmed or job.origin != "watch":
        return
    for child in _watch_split(session, job, details):
        if worker is not None and child.status in upload_jobs.WORKER_STATES:
            worker.kick(child.id, child.status)


def _watch_split(session: Session, job: UploadJob, details: dict | None) -> list[UploadJob]:
    """Dalla cartella osservata, dopo il match automatico
    (nazgarr/upload/split.py): una cartella con più stagioni diventa un upload
    per stagione, e una stagione incompleta un upload per episodio. I job
    nuovi da far partire; vuoto se il job va avanti com'è."""
    seasons = [job]
    if upload_split.seasons_enabled(session) and upload_split.seasons_to_split(job):
        seasons = _try_split(session, job, upload_split.split_seasons, details, "split_seasons_failed") or [job]
    started = []
    for season in seasons:
        episodes = None
        if season.status == "analyzing" and upload_split.enabled(session):
            if upload_split.untranslated(season, details):
                # Il conto non si sa (un episodio dei file non si traduce):
                # meglio il pack che episodi con i numeri sbagliati.
                upload_jobs.log_event(session, season, "split_skipped_untranslated", level="warning")
                session.commit()
            elif upload_split.is_incomplete(season, details):
                episodes = _try_split(session, season, upload_split.split, details, "split_failed")
        _split_decided(session, season)
        if episodes:
            started.extend(episodes)
        elif season is not job:
            started.append(season)
    return started


def _split_decided(session: Session, job: UploadJob) -> None:
    """La divisione ha guardato il job e resta com'è: via SPLIT_PENDING."""
    if job.stage == SPLIT_PENDING:
        upload_jobs.transition(session, job, "analyzing", "analyzing", stage=None)


def _split_orphans(session: Session, job: UploadJob) -> list[int]:
    """Gli upload creati da una divisione di questo job che non l'ha chiuso
    (fermata a metà da un riavvio o un kill), anche quelli delle sue parti."""
    found, level = [], [job.id]
    while level:
        level = [row_id for (row_id,) in session.query(UploadJob.id).filter(
            UploadJob.split_from_id.in_(level), UploadJob.status.in_(_UNSTARTED))]
        found += level
    return found


def _closed_by_split(job: UploadJob) -> bool:
    return any(event.code in ("job_split", "job_split_seasons") for event in job.events)


def drop_split_orphan(session: Session, job: UploadJob) -> bool:
    """Un upload creato da una divisione che si è fermata a metà (audit
    2026-10-18): il pack da cui viene non è stato chiuso dalla divisione.
    Non ha fatto niente fuori da Nazgarr e si toglie, con quelli nati da
    lui; la divisione la rifà il pack (resume_split), o il pack va avanti
    intero. Prima ripartiva da solo: un episodio, o una stagione che con la
    cartella intera si divideva di nuovo, accanto al pack. True se non c'è
    niente da fare per lui.

    Con il pack ancora in analisi non si toglie niente: la pulizia e la
    nuova divisione sono del pack (resume_split). Un kick vecchio può anche
    arrivare su un upload appena creato dalla nuova divisione con lo stesso
    id di uno tolto (SQLite riusa gli id), e lo toglieva mentre il pack si
    divideva."""
    if job.split_from_id is None or job.status not in _UNSTARTED:
        return False
    parent = session.get(UploadJob, job.split_from_id)
    if parent is None or _closed_by_split(parent):
        return False
    if parent.status == "analyzing":
        logger.info("Upload %s: la divisione di %s non è finita, ci pensa il pack", job.id, parent.id)
        return True
    ids = [job.id, *_split_orphans(session, job)]
    logger.warning("Upload %s: creato da una divisione di %s fermata a metà, si toglie", job.id, parent.id)
    session.execute(delete(UploadJob).where(UploadJob.id.in_(ids), UploadJob.status.in_(_UNSTARTED)))
    session.commit()
    return True


def drop_split_children(session: Session, job: UploadJob) -> int:
    """Gli upload creati da una divisione di questo job che non l'ha chiuso,
    ancora fermi prima della decisione (non hanno fatto niente fuori da
    Nazgarr), si tolgono con quelli nati da loro. Restituisce quanti."""
    orphans = _split_orphans(session, job) if not _closed_by_split(job) else []
    if orphans:
        session.execute(delete(UploadJob).where(UploadJob.id.in_(orphans), UploadJob.status.in_(_UNSTARTED)))
        session.commit()
    return len(orphans)


def resume_split(session: Session, job: UploadJob, worker) -> bool:
    """Prima dell'analisi di un pack: gli upload rimasti di una sua
    divisione fermata a metà si tolgono, e se la divisione della cartella
    osservata non aveva ancora deciso (SPLIT_PENDING) si rifà da capo (audit
    2026-10-18: dopo un riavvio il pack veniva analizzato intero, accanto
    agli episodi o alle stagioni già creati). True se il job è stato diviso
    (niente analisi da fare: ci pensano i nuovi, già svegliati)."""
    removed = drop_split_children(session, job)
    if removed:
        upload_jobs.log_event(session, job, "split_orphans_removed", level="warning", count=removed)
        session.commit()
    if job.stage != SPLIT_PENDING or job.status != "analyzing":
        return False
    logger.info("Upload %s: divisione fermata a metà da un riavvio, si rifà", job.id)
    try:
        details = tmdb_client(session).full_details(job.content_type, job.tmdb_id)
    except TmdbApiKeyMissingError:
        details = None
    except httpx.HTTPError:
        logger.warning("Upload %s: dettagli TMDB non disponibili per rifare la divisione", job.id, exc_info=True)
        upload_jobs.log_event(session, job, "split_seasons_failed" if job.kind == "complete_pack" else "split_failed",
                              level="warning")
        session.commit()
        _split_decided(session, job)
        return False
    for child in _watch_split(session, job, details):
        if worker is not None and child.status in upload_jobs.WORKER_STATES:
            worker.kick(child.id, child.status)
    session.refresh(job)
    return job.status != "analyzing"


def _try_split(session: Session, job: UploadJob, split, details: dict | None, failed: str) -> list[UploadJob] | None:
    """Una divisione che non riesce lascia il job com'è (è in analisi): meglio
    un pack che un upload fermo. I nuovi creati fin lì li toglie la
    divisione stessa (nazgarr/upload/split.py). Un job annullato
    dall'utente nel frattempo resta annullato, senza un "divisione non
    riuscita" che non è vero (audit 2026-10-18)."""
    try:
        return split(session, job, details)
    except Exception:
        session.rollback()
        session.refresh(job)
        if job.status != "analyzing":
            logger.info("Upload %s: annullato durante la divisione", job.id)
            return []
        logger.exception("Upload %s: divisione non riuscita", job.id)
        upload_jobs.log_event(session, job, failed, level="warning")
        session.commit()
        return None


def record_identification(session: Session, job: UploadJob, layout: SourceLayout, candidates: list[dict]) -> bool:
    """Cosa c'è nella sorgente e i candidati: il job passa al match."""
    if not upload_jobs.transition(
        session, job, "identifying", "awaiting_match",
        kind=layout.kind, content_type=layout.content_type, title=layout.title, year=layout.year,
        seasons_json=json.dumps(layout.seasons),
        episode=layout.videos[0].episodes[0] if layout.kind == "episode" and layout.videos[0].episodes else None,
        layout_json=json.dumps(asdict(layout)), candidates_json=json.dumps(candidates), stage=None,
    ):
        return False
    upload_jobs.log_event(
        session, job, "identify_done", kind=layout.kind, videos=len(layout.videos), candidates=len(candidates)
    )
    session.commit()
    return True
