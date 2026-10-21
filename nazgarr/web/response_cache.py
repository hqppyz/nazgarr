"""Cache delle risposte pesanti delle viste della libreria (Media files,
Torrent files, poster, duplicati, dashboard, Not imported): decine di
migliaia di righe, ricalcolate a ogni apertura della pagina anche quando
nulla era cambiato.

La "versione dei dati" è una generazione di processo che sale a ogni commit
che ha scritto una tabella (audit 2026-10-18): la contano gli eventi di
SQLAlchemy su ogni connessione, quindi nessuna scrittura sfugge, nemmeno un
UPDATE in place (un file tolto da un webhook di Radarr/Sonarr, un upgrade con
lo stesso nome) o un bulk upsert. Prima era un'impronta fatta a mano di
conteggi e massimi, che non vedeva quei cambi: le viste restavano vecchie fino
alla run successiva. Diventa l'ETag della risposta:
- il browser rimanda l'ETag che ha (If-None-Match): se la versione non è
  cambiata, 304 senza ricalcolare né rimandare niente;
- altrimenti si ricalcola una volta sola e la risposta resta in memoria
  finché la versione non cambia, per qualunque client.

La generazione sale solo DOPO il commit (quando la connessione torna al
pool): salendo prima, una richiesta poteva leggere la generazione nuova,
calcolare sui dati di prima del commit e tenerli sotto quella. Non contano
le tabelle che nessuna vista in cache legge e che si scrivono spesso
(_UNCACHED_TABLES: avanzamento degli upload, eventi, webhook in coda): solo
ricalcoli inutili, mai dati vecchi. Un nonce per processo nell'ETag: dopo
un riavvio la generazione riparte da zero, l'ETag di prima non vale più.
Tutto il lavoro è nello stesso processo (scheduler, worker, API): il
comando `nazgarr reset-password` scrive da fuori solo le credenziali, che
nessuna vista mostra.

Durante una run i dati cambiano continuamente (lo scan scrive, il matching
crea review): la versione è allora una finestra di RUNNING_BUCKET secondi,
così le viste restano aggiornate senza ricalcolare a ogni poll.

Un calcolo solo per chiave: le richieste uguali che arrivano mentre è in
corso aspettano il suo risultato invece di rifarlo. Alla fine di una
scansione ogni pagina aperta ricarica insieme, e i calcoli doppi in
parallelo (ognuno con tutta la libreria in memoria) portavano il processo
da ~190 a ~430 MB con 18.000 file, memoria che Python poi non restituisce
(misurato il 2026-10-10).

Memoria limitata (audit 2026-10-18): una risposta di una versione passata
non si serve più, quindi esce appena si calcola quella nuova (e un calcolo
finito dopo un commit non entra: è già passata); e le risposte
in memoria sono al massimo MAX_ENTRIES, per non più di MAX_BYTES in tutto
(le meno usate escono prima). Prima ogni filtro mai aperto teneva il suo
corpo di qualche MB fino al riavvio, e un id di tracker sempre diverso
('1', '01', '001'...) ne aggiungeva uno a richiesta.
"""

import hashlib
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from fastapi import Request, Response
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import Pool

from nazgarr.core.models import RunLog

RUNNING_BUCKET_SECONDS = 15
MAX_ENTRIES = 16
MAX_BYTES = 64 * 1024 * 1024

# Scritte spesso (l'avanzamento di un upload ogni secondo, le consegne
# delle notifiche, i webhook in coda) e mai lette dalle viste in cache: un
# loro commit non cambia la versione. Una tabella nuova conta, nel dubbio.
_UNCACHED_TABLES = frozenset({
    "upload_job", "upload_target", "upload_event", "watch_entry", "event", "event_delivery",
    "arr_webhook_event", "api_key", "tmdb_search_cache", "file_change", "file_state_snapshot",
})
_DML = re.compile(r'\s*(?:INSERT|REPLACE|UPDATE|DELETE)\b(?:\s+OR\s+\w+)?(?:\s+(?:INTO|FROM))?\s+["`\[]?(\w+)', re.I)
_READ = re.compile(r"\s*(?:SELECT|PRAGMA|EXPLAIN|BEGIN|SAVEPOINT|RELEASE|ROLLBACK|COMMIT)\b", re.I)

_NONCE = secrets.token_hex(4)
_generation = 0
_generation_lock = threading.Lock()

_lock = threading.Lock()
# chiave -> (versione, etag, corpo JSON), dalla meno usata di recente
_cache: OrderedDict[str, tuple[str, str, bytes]] = OrderedDict()
_cached_bytes = 0
_computing: dict[str, list] = {}  # chiave -> [lock di chi la calcola, quanti lo usano]
# (generazione letta, versione) dell'ultima data_version: la sola versione che
# _store accetta. Un calcolo lento su una versione già superata non entra e
# non toglie i corpi freschi.
_current: tuple[int, str] = (-1, "")

_DIRTY = "nazgarr_cache_dirty"  # nella info della connessione: ha scritto, non ancora committato
_COMMITTED = "nazgarr_cache_committed"  # ha committato una scrittura, non ancora tornata al pool


def _bump() -> None:
    global _generation
    with _generation_lock:
        _generation += 1


def _writes_cached_tables(statement: str) -> bool:
    match = _DML.match(statement)
    if match:
        return match.group(1).lower() not in _UNCACHED_TABLES
    return not _READ.match(statement)  # DDL, WITH ...: nel dubbio conta


def _info(conn) -> dict | None:
    # Una connessione invalidata (errore del driver) non ha più la sua info:
    # nessun segno, e mai un'eccezione dentro il commit o il rollback di chi scrive.
    return None if conn.invalidated else conn.info


@event.listens_for(Engine, "after_cursor_execute")
def _note_write(conn, _cursor, statement, _parameters, _context, _executemany) -> None:
    if _writes_cached_tables(statement):
        conn.info[_DIRTY] = True


@event.listens_for(Engine, "commit")
def _note_commit(conn) -> None:
    # Prima del commit vero: si segna e basta, la generazione sale al rientro
    # nel pool. Un secondo commit sulla stessa connessione ancora aperta
    # (commit "as you go") vuol dire che il primo è finito: sale adesso.
    info = _info(conn)
    if info is None:
        _bump()  # nel dubbio
        return
    if info.pop(_COMMITTED, False):
        _bump()
    if info.pop(_DIRTY, False):
        info[_COMMITTED] = True


@event.listens_for(Engine, "rollback")
def _note_rollback(conn) -> None:
    info = _info(conn)
    if info is not None:
        info.pop(_DIRTY, None)


@event.listens_for(Pool, "checkin")
def _after_commit(_dbapi_connection, connection_record) -> None:
    if connection_record is not None and connection_record.info.pop(_COMMITTED, False):
        _bump()


def data_version(session: Session) -> str:
    """La versione dei dati di tutte le viste in cache: cambia a ogni commit
    che ha scritto una tabella letta da una vista, o ogni RUNNING_BUCKET
    secondi durante una run."""
    global _current
    generation = _generation  # letta prima di ogni query: il calcolo vede almeno questi dati
    if session.query(RunLog.id).filter(RunLog.finished_at.is_(None)).first() is not None:
        version = f"{_NONCE}:running:{int(time.time() // RUNNING_BUCKET_SECONDS)}"
    else:
        version = f"{_NONCE}:{generation}"
    with _lock:
        # Solo in avanti: due richieste in parallelo possono finire la query
        # in ordine inverso, e quella con la generazione più vecchia non torna
        # versione corrente.
        if generation >= _current[0]:
            _current = (generation, version)
    return version


def cached_json(request: Request, session: Session, key: str, compute: Callable[[], object]) -> Response:
    """Risposta JSON con ETag. `key` distingue endpoint e parametri."""
    # L'URL del database nella chiave: la cache è di processo, due DB diversi
    # (es. test) con la stessa "versione" non devono mai condividere risposte.
    key = f"{session.get_bind().url}|{key}"
    version = data_version(session)
    etag = f'W/"{hashlib.sha1(f"{key}:{version}".encode(), usedforsecurity=False).hexdigest()[:20]}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}  # no-cache = rivalida sempre, via ETag
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    body = _cached_body(key, etag)
    if body is None:
        with _computing_lock(key):
            # Chi aspettava trova il risultato di chi ha calcolato prima.
            body = _cached_body(key, etag)
            if body is None:
                body = json.dumps(compute(), separators=(",", ":"), default=str).encode()
                _store(key, version, etag, body)
    return Response(content=body, media_type="application/json", headers=headers)


@contextmanager
def _computing_lock(key: str) -> Iterator[None]:
    with _lock:
        entry = _computing.setdefault(key, [threading.Lock(), 0])
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with _lock:
            entry[1] -= 1
            if entry[1] == 0:
                _computing.pop(key, None)


def _cached_body(key: str, etag: str) -> bytes | None:
    with _lock:
        hit = _cache.get(key)
        if hit is None or hit[1] != etag:
            return None
        _cache.move_to_end(key)
        return hit[2]


def _store(key: str, version: str, etag: str, body: bytes) -> None:
    global _cached_bytes
    with _lock:
        if version != _current[1]:
            # Calcolato su una versione già superata (un commit è arrivato
            # mentre calcolava, revisione dell'audit 2026-10-18): non si
            # servirà più. Prima toglieva i corpi della versione nuova già
            # in cache, da ricalcolare una volta in più.
            return
        # Una versione passata non torna mai (la generazione sale soltanto,
        # la finestra della run pure): i suoi corpi sono solo memoria.
        for old_key in [k for k, (v, _e, _b) in _cache.items() if v != version or k == key]:
            _cached_bytes -= len(_cache.pop(old_key)[2])
        _cache[key] = (version, etag, body)
        _cached_bytes += len(body)
        while len(_cache) > 1 and (len(_cache) > MAX_ENTRIES or _cached_bytes > MAX_BYTES):
            _cached_bytes -= len(_cache.popitem(last=False)[1][2])


def clear() -> None:
    global _cached_bytes
    with _lock:
        _cache.clear()
        _cached_bytes = 0
