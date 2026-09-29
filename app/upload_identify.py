"""Passo 'identifying' del flusso di upload v2 (docs/SPEC.md §9): cosa c'è
nella sorgente (app/upload_source.py) e con quale contenuto TMDB combacia.
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

from sqlalchemy.orm import Session

from app import adapter_factory, settings_repo, upload_analysis, upload_jobs
from app.adapter_factory import TmdbApiKeyMissingError
from app.models import UploadJob
from app.tmdb_client import TMDBClient
from app.upload_source import SourceLayout, scan_source

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
    seen = {(c["content_type"], c["tmdb_id"]) for c in candidates}
    for candidate in new:
        key = (candidate["content_type"], candidate["tmdb_id"])
        if key not in seen:
            seen.add(key)
            candidates.append({**candidate, "source": candidate.get("source") or source})


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


def _search_candidates(client: TMDBClient, layout: SourceLayout) -> list[dict]:
    if not layout.title:
        return []
    results = client.search_many(layout.content_type, layout.title, layout.year)
    if layout.year and not results:
        results = client.search_many(layout.content_type, layout.title)
    # Prima quelli usciti proprio nell'anno del nome, poi l'ordine di TMDB.
    if layout.year:
        results.sort(key=lambda r: r["year"] != layout.year)
    if len(results) < _OTHER_TYPE_THRESHOLD:
        other = "movie" if layout.content_type == "tv" else "tv"
        results += client.search_many(other, layout.title, layout.year)[:2]
    return results


def find_candidates(session: Session, forced: dict, layout: SourceLayout) -> list[dict]:
    try:
        client = tmdb_client(session)
    except TmdbApiKeyMissingError:
        client = None
    if forced and client is not None:
        forced_candidates = _forced_candidates(client, forced, layout)
        if forced_candidates:
            return forced_candidates[:MAX_CANDIDATES]

    candidates: list[dict] = []
    _add(candidates, _resolver_candidates(session, layout.main_video), "resolver")
    if client is not None:
        _add(candidates, _search_candidates(client, layout), "search")
    return candidates[:MAX_CANDIDATES]


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
    candidates = find_candidates(session, forced, layout)
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
