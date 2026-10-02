"""Cache delle risposte pesanti delle viste della libreria (Media files,
Torrent files, poster): decine di migliaia di righe, ricalcolate a ogni
apertura della pagina anche quando nulla era cambiato.

Una "versione dei dati" costa pochi millisecondi (aggregati su run, review,
esecuzioni, impostazioni che cambiano gli stati) e diventa l'ETag della
risposta:
- il browser rimanda l'ETag che ha (If-None-Match): se la versione non è
  cambiata, 304 senza ricalcolare né rimandare niente;
- altrimenti si ricalcola una volta sola e la risposta resta in memoria
  finché la versione non cambia, per qualunque client.

Durante una run i dati cambiano continuamente (lo scan scrive, il matching
crea review): la versione include allora una finestra di RUNNING_BUCKET
secondi, così le viste restano aggiornate senza ricalcolare a ogni poll.
"""

import hashlib
import json
import threading
import time
from collections.abc import Callable

from fastapi import Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from nazgarr.models import AppSetting, Candidate, MatchReview, MediaItem, RunLog, SeedJob, TorrentClient, Tracker

RUNNING_BUCKET_SECONDS = 15
# Impostazioni che cambiano stati o contenuti delle viste senza una run.
_VERSIONED_SETTINGS = ("exclusion_patterns", "exclusion_presets", "rematch_interval_days")

_lock = threading.Lock()
_cache: dict[str, tuple[str, bytes]] = {}  # chiave -> (etag, corpo JSON)


def data_version(session: Session) -> str:
    runs = session.query(func.max(RunLog.id), func.max(RunLog.finished_at), func.count(RunLog.id)).one()
    running = session.query(RunLog.id).filter(RunLog.finished_at.is_(None)).count()
    reviews = session.query(
        func.count(MatchReview.id), func.max(MatchReview.id), func.max(MatchReview.decided_at)
    ).one()
    jobs = session.query(
        func.count(SeedJob.id), func.max(SeedJob.id), func.max(SeedJob.torrent_added_at),
        func.sum(func.length(SeedJob.final_status)), func.count(SeedJob.recheck_status),
    ).one()
    candidates = session.query(func.max(Candidate.id)).scalar()
    items = session.query(func.count(MediaItem.id), func.max(MediaItem.id)).one()
    settings = dict(
        session.query(AppSetting.key, AppSetting.value).filter(AppSetting.key.in_(_VERSIONED_SETTINGS)).all()
    )
    # Il filtro per tracker (nazgarr/tracker_scope.py) dipende da URL e stato dei
    # tracker e dallo stato dei client: un loro cambio cambia le viste.
    trackers = (
        session.query(Tracker.id, Tracker.announce_url, Tracker.base_url, Tracker.enabled).order_by(Tracker.id).all()
    )
    clients = session.query(TorrentClient.id, TorrentClient.enabled).order_by(TorrentClient.id).all()
    parts = [runs, reviews, jobs, candidates, items, sorted(settings.items()), trackers, clients]
    if running:
        parts.append(("running", int(time.time() // RUNNING_BUCKET_SECONDS)))
    return hashlib.sha1(repr(parts).encode()).hexdigest()


def cached_json(request: Request, session: Session, key: str, compute: Callable[[], object]) -> Response:
    """Risposta JSON con ETag. `key` distingue endpoint e parametri."""
    # L'URL del database nella chiave: la cache è di processo, due DB diversi
    # (es. test) con la stessa "versione" non devono mai condividere risposte.
    key = f"{session.get_bind().url}|{key}"
    etag = f'W/"{hashlib.sha1(f"{key}:{data_version(session)}".encode()).hexdigest()[:20]}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}  # no-cache = rivalida sempre, via ETag
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    with _lock:
        hit = _cache.get(key)
    if hit is not None and hit[0] == etag:
        body = hit[1]
    else:
        body = json.dumps(compute(), separators=(",", ":"), default=str).encode()
        with _lock:
            _cache[key] = (etag, body)
    return Response(content=body, media_type="application/json", headers=headers)


def clear() -> None:
    with _lock:
        _cache.clear()
