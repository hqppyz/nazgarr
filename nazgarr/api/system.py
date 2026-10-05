"""Endpoint di introspezione sull'istanza in esecuzione, per la tab
Configuration > Application (versione/runtime + controllo aggiornamenti)
e Configuration > Logs (docs/SPEC.md non ne parla ancora: aggiunta su
richiesta esplicita, non collegata a nessuna fase del roadmap)."""

import platform
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr.core import updates
from nazgarr.core.config import Settings
from nazgarr.core.version import __commit__, __version__
from nazgarr.library import setup_status as setup_status_module
from nazgarr.web.deps import get_session, get_settings

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
    last = updates.last_check(session)
    return UpdateCheckResponse(**last) if last else None


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


class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str


class LogsResponse(BaseModel):
    entries: list[LogEntry]
    available: bool  # false se il file di log non esiste ancora (avvio appena fatto)


@router.get("/logs", response_model=LogsResponse)
def logs(min_level: str = "INFO", settings: Settings = Depends(get_settings)):
    log_path = Path(settings.data_dir) / "logs" / "nazgarr.log"
    if not log_path.exists():
        return LogsResponse(entries=[], available=False)

    min_index = _LEVEL_ORDER.index(min_level) if min_level in _LEVEL_ORDER else 0
    entries: list[LogEntry] = []
    for line in log_path.read_text(errors="replace").splitlines():
        match = _LOG_LINE_RE.match(line)
        if match:
            timestamp, level, logger_name, message = match.groups()
            entries.append(LogEntry(timestamp=timestamp, level=level, logger=logger_name, message=message))
        elif entries:
            # riga di continuazione (es. traceback multi-riga): si appende
            # all'ultima entry invece di diventarne una fasulla a sé.
            entries[-1].message += "\n" + line

    filtered = [e for e in entries if e.level in _LEVEL_ORDER and _LEVEL_ORDER.index(e.level) >= min_index]
    return LogsResponse(entries=list(reversed(filtered[-_MAX_LOG_ENTRIES:])), available=True)


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
