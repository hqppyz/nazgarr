"""Endpoint di introspezione sull'istanza in esecuzione, per la tab
Configuration > Application (versione/runtime + controllo aggiornamenti)
e Configuration > Logs (docs/SPEC.md non ne parla ancora: aggiunta su
richiesta esplicita, non collegata a nessuna fase del roadmap)."""

import platform
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr import setup_status as setup_status_module
from nazgarr.config import Settings
from nazgarr.deps import get_session, get_settings
from nazgarr.version import __commit__, __version__

router = APIRouter(prefix="/api/system", tags=["system"])

GITHUB_REPO = "lktorrentz/nazgarr"


class AppInfoResponse(BaseModel):
    version: str
    commit: str | None = None
    python_version: str
    platform: str
    started_at: datetime


@router.get("/info", response_model=AppInfoResponse)
def app_info(request: Request):
    return AppInfoResponse(
        version=__version__,
        commit=__commit__,
        python_version=platform.python_version(),
        platform=f"{platform.system().lower()}/{platform.machine()}",
        started_at=request.app.state.started_at,
    )


class UpdateCheckResponse(BaseModel):
    current_version: str
    latest_version: str | None
    update_available: bool
    checked_at: datetime
    note: str | None = None
    channel: str | None = None  # "stable" | "test": con quali release si è confrontato


def _parse_version(version: str) -> tuple[int, ...]:
    """Confronto minimale X.Y.Z, senza dipendenza da una libreria semver —
    unico schema che questo progetto usa (nazgarr/version.py)."""
    parts = []
    for chunk in version.lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _channel_and_latest(releases: list[dict], current: str) -> tuple[str, str | None]:
    """Canale dedotto dalla versione in uso: se è una release stable (non
    prerelease) si confronta solo con le stable, così chi prova l'app su
    :stable non viene avvisato di ogni build di test; altrimenti (build di
    test, :nightly) con la più recente in assoluto."""
    published = [r for r in releases if not r.get("draft") and r.get("tag_name")]
    stable = [r for r in published if not r.get("prerelease")]
    # Uguaglianza esatta del tag: "0.3.0-dev" (sviluppo locale) non è la stable 0.3.0.
    on_stable = any(r["tag_name"].lstrip("vV") == current.lstrip("vV") for r in stable)
    pool = stable if on_stable else published
    newest = max(pool, key=lambda r: _parse_version(r["tag_name"]), default=None)
    return ("stable" if on_stable else "test"), (newest["tag_name"] if newest else None)


@router.get("/update-check", response_model=UpdateCheckResponse)
def update_check():
    """Chiamata solo su richiesta esplicita dell'utente (bottone "Check for
    updates" in UI), mai in automatico. Confronta con le GitHub Release: la
    CI ne crea una (prerelease) a ogni push su main, il canale stable si
    aggiorna a mano (nazgarr/version.py)."""
    now = datetime.now(UTC)
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases",
            params={"per_page": 50},
            headers={"Accept": "application/vnd.github+json", "User-Agent": "nazgarr"},
            timeout=5,
            follow_redirects=True,  # un repo rinominato risponde con un redirect
        )
    except httpx.HTTPError as exc:
        return UpdateCheckResponse(
            current_version=__version__, latest_version=None, update_available=False,
            checked_at=now, note=f"Could not reach GitHub: {exc}",
        )

    if response.status_code != 200:
        return UpdateCheckResponse(
            current_version=__version__, latest_version=None, update_available=False,
            checked_at=now, note=f"GitHub returned HTTP {response.status_code}.",
        )

    channel, latest = _channel_and_latest(response.json(), __version__)
    if latest is None:
        return UpdateCheckResponse(
            current_version=__version__, latest_version=None, update_available=False,
            checked_at=now, note="No releases published yet.", channel=channel,
        )
    update_available = _parse_version(latest) > _parse_version(__version__)
    return UpdateCheckResponse(
        current_version=__version__, latest_version=latest,
        update_available=update_available, checked_at=now, channel=channel,
    )


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
    (nazgarr/setup_status.py): cosa è già configurato, dalla configurazione reale."""
    return setup_status_module.setup_status(session)
