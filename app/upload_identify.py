"""Passo 'identifying' del flusso di upload v2 (docs/SPEC.md §9): cosa c'è
nella sorgente (app/upload_source.py) e con quale contenuto dei metadati
combacia. Porta il job al primo punto di approvazione, awaiting_match.

Nessun candidato non è un errore: l'utente può sempre forzare un id o
cercare a mano dalla schermata di match.
"""

import json
import logging
from dataclasses import asdict

from sqlalchemy.orm import Session

from app import adapter_factory, upload_jobs
from app.adapter_factory import TmdbApiKeyMissingError
from app.models import UploadJob
from app.upload_source import scan_source

logger = logging.getLogger(__name__)


def _resolver_candidates(session: Session, main_video: str) -> list[dict]:
    try:
        resolver = adapter_factory.build_media_resolver(session)
    except TmdbApiKeyMissingError:
        return []
    resolved = resolver.resolve(main_video)
    if resolved is None:
        return []
    return [{
        "tmdb_id": resolved.tmdb_id,
        "content_type": resolved.content_type,
        "title": resolved.title,
        "year": resolved.year,
        "poster_path": resolved.poster_path,
        "imdb_id": resolved.imdb_id,
        "source": resolved.source or resolver.SOURCE,
    }]


def handle(session: Session, job: UploadJob, worker) -> None:
    upload_jobs.log_event(session, job, "identify_started")
    session.commit()
    try:
        layout = scan_source(job.source_path)
    except ValueError as exc:
        raise upload_jobs.UploadJobError(str(exc)) from exc
    except OSError as exc:
        raise upload_jobs.UploadJobError("upload_source_unreadable", error=str(exc)) from exc

    candidates = _resolver_candidates(session, layout.main_video)
    if upload_jobs.transition(
        session, job, "identifying", "awaiting_match",
        kind=layout.kind, content_type=layout.content_type, title=layout.title, year=layout.year,
        seasons_json=json.dumps(layout.seasons), layout_json=json.dumps(asdict(layout)),
        candidates_json=json.dumps(candidates), stage=None,
    ):
        upload_jobs.log_event(
            session, job, "identify_done", kind=layout.kind, videos=len(layout.videos), candidates=len(candidates)
        )
        session.commit()
