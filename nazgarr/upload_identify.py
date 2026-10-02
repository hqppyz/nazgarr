"""Passo 'identifying' del flusso di upload v2 (docs/SPEC.md §9): cosa c'è
nella sorgente (nazgarr/upload_source.py) e con quale contenuto TMDB combacia.
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
from sqlalchemy.orm import Session

from nazgarr import adapter_factory, settings_repo, upload_analysis, upload_jobs, upload_match_score
from nazgarr.adapter_factory import TmdbApiKeyMissingError
from nazgarr.models import UploadJob
from nazgarr.tmdb_client import TMDBClient
from nazgarr.upload_source import SourceLayout, scan_source

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 8
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
    # tradotti per il confronto ("titles", nazgarr/upload_match_score.py), e
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
            return upload_match_score.scored(forced_candidates[:MAX_CANDIDATES], layout.title, layout.year,
                                             layout.content_type)

    candidates: list[dict] = []
    _add(candidates, _resolver_candidates(session, layout.main_video), "resolver")
    if client is not None:
        _add(candidates, _search_candidates(client, layout, languages), "search")
    # Ognuno con la sua confidence (nazgarr/upload_match_score.py), dal più sicuro.
    return upload_match_score.scored(candidates[:MAX_CANDIDATES], layout.title, layout.year, layout.content_type)


AUTO_MATCH_SETTING = "upload_auto_match_threshold"
DEFAULT_AUTO_MATCH_THRESHOLD = 0.9


def auto_match_threshold(session: Session) -> float | None:
    """La confidence oltre la quale un upload conferma da solo il match
    (Settings > Upload). Mai salvata = 0.9; 0 = spento."""
    raw = settings_repo.get_setting(session, AUTO_MATCH_SETTING)
    if raw in (None, ""):
        return DEFAULT_AUTO_MATCH_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_AUTO_MATCH_THRESHOLD
    return value if 0 < value <= 1 else None


def _auto_match(session: Session, job: UploadJob, candidates: list[dict]) -> None:
    """Per ogni upload, dalla cartella osservata o creato a mano (decisione
    dell'utente, 2026-10-02): il candidato più sicuro, se supera la soglia, si
    conferma da solo, con gli stessi controlli della conferma a mano. Sotto
    soglia, se è ambiguo o se qualcosa non torna (tipo, stagione), il job
    aspetta al match come sempre. Dalla decisione si torna indietro con
    "Change match" (back_to_match)."""
    if not candidates:
        return
    best = candidates[0]
    threshold = auto_match_threshold(session)
    if threshold is None:
        return  # spento: niente da dire nel registro
    if best.get("ambiguous") or best.get("confidence", 0) < threshold:
        upload_jobs.log_event(session, job, "auto_match_skipped", confidence=best.get("confidence", 0),
                              threshold=threshold)
        session.commit()
        return
    try:
        details = tmdb_client(session).full_details(best["content_type"], best["tmdb_id"])
    except TmdbApiKeyMissingError:
        details = None
    except httpx.HTTPError:
        logger.warning("Dettagli TMDB non disponibili per il match automatico del job %s", job.id, exc_info=True)
        upload_jobs.log_event(session, job, "auto_match_failed", level="warning")
        session.commit()
        return
    try:
        upload_jobs.confirm_match(
            session, job, content_type=best["content_type"], tmdb_id=best["tmdb_id"], kind=job.kind,
            seasons=json.loads(job.seasons_json or "[]"), episode=job.episode, details=details,
            forced=json.loads(job.forced_ids_json or "{}"),
        )
    except upload_jobs.UploadJobError as exc:
        session.rollback()
        upload_jobs.log_event(session, job, "auto_match_failed", level="warning", reason=exc.code)
        session.commit()
        return
    upload_jobs.log_event(session, job, "auto_matched", confidence=best["confidence"], title=job.title,
                          year=job.year)
    session.commit()


def handle(session: Session, job: UploadJob, worker) -> None:
    upload_jobs.log_event(session, job, "identify_started")
    session.commit()
    try:
        layout = scan_source(job.source_path)
    except ValueError as exc:
        raise upload_jobs.UploadJobError(str(exc)) from exc
    except OSError as exc:
        raise upload_jobs.UploadJobError("upload_source_unreadable", error=str(exc)) from exc

    forced = json.loads(job.forced_ids_json or "{}")
    # Le lingue dei tracker del job, oltre all'inglese di TMDB.
    languages = tuple(sorted({t.tracker.language for t in job.targets if t.tracker.language} - {"en"}))
    candidates = find_candidates(session, forced, layout, languages)
    if upload_jobs.transition(
        session, job, "identifying", "awaiting_match",
        kind=layout.kind, content_type=layout.content_type, title=layout.title, year=layout.year,
        seasons_json=json.dumps(layout.seasons),
        episode=layout.videos[0].episodes[0] if layout.kind == "episode" and layout.videos[0].episodes else None,
        layout_json=json.dumps(asdict(layout)), candidates_json=json.dumps(candidates), stage=None,
    ):
        upload_jobs.log_event(
            session, job, "identify_done", kind=layout.kind, videos=len(layout.videos), candidates=len(candidates)
        )
        session.commit()
        _auto_match(session, job, candidates)
