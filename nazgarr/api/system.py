"""Endpoint di introspezione sull'istanza in esecuzione, per la tab
Configuration > Application (versione/runtime + controllo aggiornamenti)
e Configuration > Logs (docs/SPEC.md non ne parla ancora: aggiunta su
richiesta esplicita, non collegata a nessuna fase del roadmap)."""

import logging
import os
import platform
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from nazgarr.core import updates
from nazgarr.core.config import Settings
from nazgarr.core.logs import redact
from nazgarr.core.version import __commit__, __version__
from nazgarr.library import setup_status as setup_status_module
from nazgarr.web.deps import get_session, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])



class AppInfoResponse(BaseModel):
    version: str
    commit: str | None = None
    python_version: str
    platform: str
    started_at: datetime


class WhoAmIResponse(BaseModel):
    kind: str  # user | api_key
    name: str | None
    level: str  # write | read


@router.get("/whoami", response_model=WhoAmIResponse)
def whoami(request: Request, session: Session = Depends(get_session)):
    """Chi sta chiamando: il login o una API key, e cosa può fare. Serve a
    un'altra istanza che usa una nostra chiave (nazgarr/integrations/instances.py) per
    sapere se è di lettura o di scrittura."""
    from nazgarr.core.models import ApiKey

    key_id = getattr(request.state, "api_key_id", None)
    if key_id is None:
        return WhoAmIResponse(kind="user", name=None, level="write")
    key = session.get(ApiKey, key_id)
    return WhoAmIResponse(kind="api_key", name=key.name if key else None, level=key.level if key else "read")


@router.get("/info", response_model=AppInfoResponse)
def app_info(request: Request):
    return AppInfoResponse(
        version=__version__,
        commit=__commit__,
        python_version=platform.python_version(),
        platform=f"{platform.system().lower()}/{platform.machine()}",
        started_at=request.app.state.started_at,
    )


class ReleaseNote(BaseModel):
    """Una voce di nazgarr/release_notes.json: per lingua ("it", "en")."""
    version: str
    date: str | None = None
    breaking: dict[str, list[str]] = {}  # cosa fare prima o dopo l'aggiornamento
    highlights: dict[str, list[str]] = {}  # le novità
    fixes: dict[str, list[str]] = {}  # i bug corretti (le chores solo in CHANGELOG.md)


class UpdateCheckResponse(BaseModel):
    current_version: str
    latest_version: str | None
    update_available: bool
    checked_at: datetime
    note: str | None = None
    channel: str | None = None  # "stable" | "test": con quali release si è confrontato
    # Le note delle versioni più nuove di quella in uso, fino all'ultima:
    # i cambiamenti che rompono qualcosa si vedono prima di aggiornare.
    notes: list[ReleaseNote] = []


@router.get("/update-check", response_model=UpdateCheckResponse)
def update_check(session: Session = Depends(get_session)):
    """Su richiesta dell'utente ("Controlla aggiornamenti"): chiama GitHub e
    salva l'esito, lo stesso che il controllo automatico (se acceso) rinnova
    ogni 12 ore (nazgarr/core/updates.py)."""
    return UpdateCheckResponse(**updates.check(session))


@router.get("/update-status", response_model=UpdateCheckResponse | None)
def update_status(session: Session = Depends(get_session)):
    """L'ultimo esito salvato, senza chiamare GitHub: per l'avviso nella
    barra laterale. None se non c'è o riguardava un'altra versione."""
    try:
        # Anche last_check sta dentro: legge l'esito con .get(), e un valore
        # salvato che non è un oggetto JSON (es. [1]) lo fa cadere.
        last = updates.last_check(session)
        if not last:
            return None
        if not isinstance(last, dict):
            raise TypeError("not an object")
        return UpdateCheckResponse(**last)
    except (TypeError, ValidationError, AttributeError, KeyError):
        # Un esito salvato che non ha la forma attesa (di una versione di
        # prima, o scritto a mano): nessun avviso, invece di un 500 a ogni
        # pagina (audit 2026-10-18). "Controlla aggiornamenti" lo riscrive,
        # e anche quello automatico: per check_if_due un esito senza un
        # checked_at leggibile vale come nessun controllo.
        logger.warning("Esito salvato del controllo degli aggiornamenti illeggibile: ignorato")
        return None


class ReleaseNotesResponse(BaseModel):
    current_version: str
    entries: list[ReleaseNote]  # quelle non ancora viste, dalla più nuova


@router.get("/release-notes", response_model=ReleaseNotesResponse)
def release_notes(session: Session = Depends(get_session)):
    """Le note delle versioni arrivate dall'ultima vista: la UI le mostra
    una volta dopo un aggiornamento."""
    return ReleaseNotesResponse(current_version=__version__, entries=updates.unseen_notes(session))


@router.post("/release-notes/seen", status_code=204)
def release_notes_seen(session: Session = Depends(get_session)):
    updates.mark_seen(session)


_LOG_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\S+)\s+([^:]+): (.*)$")
_LEVEL_ORDER = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_MAX_LOG_ENTRIES = 500
# Quanto leggere alla volta dalla fine del file.
_TAIL_CHUNK_BYTES = 256 * 1024


class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str


class LogsResponse(BaseModel):
    entries: list[LogEntry]
    available: bool  # false se il file di log non esiste ancora (avvio appena fatto)


def _lines_backwards(path: Path, chunk_bytes: int):
    """Le righe del file dall'ultima alla prima, leggendo a blocchi dalla
    fine: le ultime 500 voci stanno quasi sempre nel primo blocco, e il
    file (fino a 5 MB) non si legge più intero a ogni poll. Si divide solo
    sugli a capo, quindi un carattere UTF-8 non si spezza mai fra due blocchi."""
    with path.open("rb") as f:
        position = f.seek(0, os.SEEK_END)
        rest = b""
        first = True
        while position > 0:
            size = min(chunk_bytes, position)
            position -= size
            f.seek(position)
            lines = (f.read(size) + rest).split(b"\n")
            # La prima può essere a metà: si completa col blocco precedente.
            rest = lines.pop(0) if position > 0 else b""
            if first:
                first = False
                if lines and lines[-1] == b"":
                    lines.pop()  # l'a capo finale del file
            for raw in reversed(lines):
                yield raw.decode("utf-8", errors="replace").rstrip("\r")


def read_log_entries(path: Path, min_level: str, limit: int = _MAX_LOG_ENTRIES,
                     chunk_bytes: int = _TAIL_CHUNK_BYTES) -> list[LogEntry]:
    """Le ultime `limit` voci almeno di `min_level`, dalla più nuova. Una riga
    che non apre una voce (es. un traceback su più righe) appartiene a quella
    sopra: leggendo dal fondo si tiene da parte finché non arriva la sua."""
    min_index = _LEVEL_ORDER.index(min_level) if min_level in _LEVEL_ORDER else 0
    entries: list[LogEntry] = []
    continuation: list[str] = []
    for line in _lines_backwards(path, chunk_bytes):
        match = _LOG_LINE_RE.match(line)
        if not match:
            continuation.append(line)
            continue
        timestamp, level, logger_name, message = match.groups()
        if continuation:
            message += "\n" + "\n".join(reversed(continuation))
            continuation.clear()
        if level in _LEVEL_ORDER and _LEVEL_ORDER.index(level) >= min_index:
            # Ripulita anche in uscita: le righe scritte prima degli schemi
            # nuovi (token di Telegram e Discord, utente:password@) restano
            # nel file finché non ruota, e la tab Logs la legge anche una
            # API key di sola lettura (audit 2026-10-18).
            entries.append(LogEntry(timestamp=timestamp, level=level, logger=logger_name, message=redact(message)))
            if len(entries) >= limit:
                break
    # Righe prima della prima voce del file: di nessuno, come prima.
    return entries


@router.get("/logs", response_model=LogsResponse)
def logs(min_level: str = "INFO", settings: Settings = Depends(get_settings)):
    """Le ultime voci del log per la tab Logs, che le chiede ogni 10 s: dalla
    fine del file, senza rileggerlo e analizzarlo tutto (audit 2026-10-18)."""
    log_path = Path(settings.data_dir) / "logs" / "nazgarr.log"
    if not log_path.exists():
        return LogsResponse(entries=[], available=False)
    return LogsResponse(entries=read_log_entries(log_path, min_level), available=True)


class SetupStep(BaseModel):
    done: bool
    count: int | None = None
    linked: int | None = None
    trackers: int | None = None
    image_hosts: int | None = None


class SetupStatusResponse(BaseModel):
    steps: dict[str, SetupStep]
    required: list[str]
    optional: list[str]
    complete: bool


@router.get("/setup-status", response_model=SetupStatusResponse)
def setup_status(session: Session = Depends(get_session)):
    """Per la checklist "Getting started" e il tour del primo accesso
    (nazgarr/library/setup_status.py): cosa è già configurato, dalla configurazione reale."""
    return setup_status_module.setup_status(session)
