"""Controllo degli aggiornamenti e note di rilascio (decisione dell'utente,
2026-10-05).

- Il controllo confronta la versione in uso con le GitHub Release. Si fa a
  mano (Impostazioni › Applicazione) o, se l'utente accende
  update_check_auto (spento di default), ogni CHECK_INTERVAL dallo scheduler
  (nazgarr/scheduler.py). L'esito resta in app_settings.update_check_last:
  la UI lo legge senza chiamare GitHub.
- Le note di rilascio sintetiche stanno in nazgarr/release_notes.json, una
  voce per versione stable (punti salienti e cambiamenti che rompono qualcosa,
  in italiano e in inglese), proposte da Claude e approvate dall'utente prima
  di ogni promozione. Quelle dettagliate in CHANGELOG.md.
  Dopo un aggiornamento la UI mostra le voci fra la versione vista l'ultima
  volta (release_notes_seen) e quella in uso; prima di aggiornare, il
  controllo legge il file della versione nuova al suo tag, per avvisare dei
  cambiamenti che rompono qualcosa. Nazgarr non si aggiorna da solo: lo fa
  Docker, Unraid o pipx.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from nazgarr.core import settings_repo
from nazgarr.core.version import __version__

logger = logging.getLogger(__name__)

GITHUB_REPO = "lktorrentz/nazgarr"
NOTES_FILE = Path(__file__).resolve().parent.parent / "release_notes.json"
CHECK_INTERVAL = timedelta(hours=12)
LAST_CHECK_KEY = "update_check_last"
SEEN_KEY = "release_notes_seen"
AUTO_KEY = "update_check_auto"


def parse_version(version: str) -> tuple[int, ...]:
    """Confronto minimale X.Y.Z, senza dipendenza da una libreria semver —
    unico schema che questo progetto usa (nazgarr/core/version.py)."""
    parts = []
    for chunk in version.lstrip("vV").split("-")[0].split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def channel_and_latest(releases: list[dict], current: str) -> tuple[str, str | None]:
    """Canale dedotto dalla versione in uso: se è una release stable (non
    prerelease) si confronta solo con le stable, così chi prova l'app su
    :stable non viene avvisato di ogni build di test; altrimenti (build di
    test, :nightly) con la più recente in assoluto."""
    published = [r for r in releases if not r.get("draft") and r.get("tag_name")]
    stable = [r for r in published if not r.get("prerelease")]
    # Uguaglianza esatta del tag: "0.3.0-dev" (sviluppo locale) non è la stable 0.3.0.
    on_stable = any(r["tag_name"].lstrip("vV") == current.lstrip("vV") for r in stable)
    pool = stable if on_stable else published
    newest = max(pool, key=lambda r: parse_version(r["tag_name"]), default=None)
    return ("stable" if on_stable else "test"), (newest["tag_name"] if newest else None)


def notes_between(entries: list[dict], after: str | None, up_to: str) -> list[dict]:
    """Le voci con after < versione <= up_to, dalla più nuova."""
    low = parse_version(after) if after else (-1,)
    high = parse_version(up_to)
    picked = [e for e in entries if e.get("version") and low < parse_version(e["version"]) <= high]
    return sorted(picked, key=lambda e: parse_version(e["version"]), reverse=True)


def bundled_notes() -> list[dict]:
    try:
        return json.loads(NOTES_FILE.read_text(encoding="utf-8")).get("entries", [])
    except (OSError, ValueError):
        logger.warning("Note di rilascio non leggibili: %s", NOTES_FILE, exc_info=True)
        return []


def _remote_notes(tag: str) -> list[dict]:
    """Le note della versione nuova, dal suo tag: prima di aggiornare."""
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{tag}/nazgarr/release_notes.json"
    try:
        response = httpx.get(url, headers={"User-Agent": "nazgarr"}, timeout=5, follow_redirects=True)
        if response.status_code != 200:
            return []
        return response.json().get("entries", [])
    except (httpx.HTTPError, ValueError):
        return []


def check(session: Session, now: datetime | None = None) -> dict:
    """Chiama GitHub, salva l'esito in update_check_last e lo restituisce."""
    now = now or datetime.now(UTC)
    result: dict = {"current_version": __version__, "latest_version": None, "update_available": False,
                    "checked_at": now.isoformat(), "note": None, "channel": None, "notes": []}
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases",
            params={"per_page": 50},
            headers={"Accept": "application/vnd.github+json", "User-Agent": "nazgarr"},
            timeout=5,
            follow_redirects=True,  # un repo rinominato risponde con un redirect
        )
    except httpx.HTTPError as exc:
        result["note"] = f"Could not reach GitHub: {exc}"
        return result  # un errore di rete non sovrascrive l'ultimo esito buono
    if response.status_code != 200:
        result["note"] = f"GitHub returned HTTP {response.status_code}."
        return result
    channel, latest = channel_and_latest(response.json(), __version__)
    result.update(channel=channel, latest_version=latest)
    if latest is None:
        result["note"] = "No releases published yet."
    elif parse_version(latest) > parse_version(__version__):
        result["update_available"] = True
        result["notes"] = notes_between(_remote_notes(latest), __version__, latest)
    settings_repo.set_setting(session, LAST_CHECK_KEY, json.dumps(result))
    return result


def last_check(session: Session) -> dict | None:
    """L'ultimo esito salvato, se riguarda ancora questa versione."""
    raw = settings_repo.get_setting(session, LAST_CHECK_KEY)
    try:
        result = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not result or result.get("current_version") != __version__:
        return None  # aggiornato nel frattempo: quell'esito non vale più
    return result


def check_if_due(session: Session, now: datetime | None = None) -> bool:
    """Dallo scheduler: solo con update_check_auto acceso e se l'ultimo
    controllo ha più di CHECK_INTERVAL."""
    from nazgarr.core import settings_registry

    if not settings_registry.get_bool(session, AUTO_KEY):
        return False
    now = now or datetime.now(UTC)
    last = last_check(session)
    if last and now - datetime.fromisoformat(last["checked_at"]) < CHECK_INTERVAL:
        return False
    check(session, now)
    return True


def unseen_notes(session: Session) -> list[dict]:
    """Le note fra l'ultima versione vista e quella in uso."""
    return notes_between(bundled_notes(), settings_repo.get_setting(session, SEEN_KEY), __version__)


def mark_seen(session: Session) -> None:
    settings_repo.set_setting(session, SEEN_KEY, __version__)


def init_seen(session: Session) -> None:
    """All'avvio: un'installazione nuova (o di prima delle note) parte da
    questa versione, senza mostrare note di versioni mai usate."""
    if settings_repo.get_setting(session, SEEN_KEY) is None:
        mark_seen(session)
