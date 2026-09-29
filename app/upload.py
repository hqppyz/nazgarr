"""Orchestrazione del modulo Upload (docs/SPEC.md §9, Fase 6): dato un
file locale, identifica il contenuto, crea il .torrent, genera
mediainfo/screenshot, compila la descrizione dal profilo del tracker ed
espone il dupe-check — fino al punto della conferma umana obbligatoria,
mai oltre (l'invio vero è submit(), chiamato solo da
app/api/uploads.py::confirm dopo la conferma esplicita). Dominio separato
dal reseeding: non tocca mai media_item/candidate/match_review/seed_job."""

import json
import logging
import os

import guessit
from jinja2 import Template
from sqlalchemy.orm import Session

from app import mediainfo_util, screenshots, settings_repo, torrent_create
from app.adapters.image_host.base import ImageHostAdapter, ImageHostError
from app.adapters.media_resolver.base import MediaResolverAdapter
from app.adapters.tracker.base import TorrentCandidate, TrackerAdapter, UploadError, UploadFields
from app.api_errors import CodedError
from app.content_type_guess import guess_content_type_from_guessit
from app.models import Tracker, TrackerUploadProfile, UploadJob

logger = logging.getLogger(__name__)

# Mapping da segnali guessit a chiavi type_id — euristica best-effort,
# MAI la fonte di verità: category_id/resolution_id si ricavano in modo
# affidabile (content_type risolto, screen_size di guessit combacia quasi
# sempre con le chiavi resolution_id_map), ma la distinzione
# REMUX/ENCODE/WEBDL/BDMUX/ecc. dipende da convenzioni di release troppo
# sfumate per un guess automatico affidabile — per questo type_id resta
# sempre modificabile sulla riga upload_job prima della conferma (docs/SPEC.md
# §9: "risolti, modificabili prima dell'invio"), mai bloccante di per sé.
_DEFAULT_TYPE_GUESS = "ENCODE"


class UploadPreparationError(CodedError):
    """Errore non recuperabile prima ancora di provare l'invio — es. tracker
    senza announce_url configurato, o senza un profilo di upload. Sollevata
    solo prima di scrivere su job.error_message (mai catturata per essere
    ri-memorizzata come testo), quindi può restare un CodedError puro."""


def _guess_content_type(source_path: str) -> str:
    return guess_content_type_from_guessit(guessit.guessit(source_path))


def _guess_release_type_key(source_path: str, type_map: dict) -> str | None:
    guess = guessit.guessit(source_path)
    other = guess.get("other")
    others = {other} if isinstance(other, str) else set(other or [])
    source = str(guess.get("source") or "").lower()

    if "Remux" in others and "REMUX" in type_map:
        return "REMUX"
    if source == "web" and "WEBDL" in type_map:
        return "WEBDL"
    if source == "hdtv" and "HDTV" in type_map:
        return "HDTV"
    if source == "dvd" and "DVDRIP" in type_map:
        return "DVDRIP"
    return _DEFAULT_TYPE_GUESS if _DEFAULT_TYPE_GUESS in type_map else None


def create_draft(
    session: Session,
    source_path: str,
    tracker: Tracker,
    resolver: MediaResolverAdapter | None,
    media_file_id: int | None = None,
) -> UploadJob:
    content_type = _guess_content_type(source_path)
    tmdb_id = None
    if resolver is not None:
        try:
            resolved = resolver.resolve(source_path, content_type)
        except Exception:
            logger.exception("Risoluzione contenuto fallita per l'upload di %r", source_path)
            resolved = None
        if resolved is not None:
            tmdb_id = resolved.tmdb_id

    job = UploadJob(
        media_file_id=media_file_id, source_path=source_path, tracker_id=tracker.id, status="draft", tmdb_id=tmdb_id
    )
    session.add(job)
    session.commit()
    return job


def prepare(
    session: Session,
    job: UploadJob,
    tracker: Tracker,
    profile: TrackerUploadProfile,
    image_host_chain: ImageHostAdapter,
    data_dir: str,
) -> UploadJob:
    """Passi 3-6 di docs/SPEC.md §9 (.torrent, mediainfo, screenshot,
    descrizione). Porta la riga a status='ready' — mai oltre, submit()
    richiede sempre la conferma umana esplicita a monte."""
    if not tracker.announce_url:
        raise UploadPreparationError("tracker_missing_announce_url", tracker=tracker.label)

    job_dir = os.path.join(data_dir, "uploads", str(job.id))
    os.makedirs(job_dir, exist_ok=True)

    torrent_path, info_hash = torrent_create.create_torrent(
        job.source_path, tracker.announce_url, os.path.join(job_dir, "upload.torrent")
    )
    job.torrent_path = torrent_path
    job.info_hash = info_hash
    job.mediainfo_text = mediainfo_util.extract_full_text(job.source_path)

    screenshot_count = int(settings_repo.get_setting(session, "upload_screenshot_count") or "4")
    tonemap_hdr = (settings_repo.get_setting(session, "upload_tonemap_hdr") or "").lower() == "true"

    screenshot_urls: list[str] = []
    try:
        shot_paths = screenshots.generate_screenshots(
            job.source_path, os.path.join(job_dir, "screenshots"), count=screenshot_count, tonemap=tonemap_hdr
        )
    except screenshots.ScreenshotError:
        logger.exception("Generazione screenshot fallita per %r", job.source_path)
        shot_paths = []
    for path in shot_paths:
        try:
            screenshot_urls.append(image_host_chain.upload(path))
        except ImageHostError:
            logger.exception("Upload screenshot fallito per %r", path)
    job.screenshot_urls_json = json.dumps(screenshot_urls)

    category_map = json.loads(profile.category_id_map_json or "{}")
    type_map = json.loads(profile.type_id_map_json or "{}")
    resolution_map = json.loads(profile.resolution_id_map_json or "{}")

    content_type = _guess_content_type(job.source_path)
    job.category_id = category_map.get(content_type)
    type_key = _guess_release_type_key(job.source_path, type_map)
    job.type_id = type_map.get(type_key) if type_key else None
    screen_size = guessit.guessit(job.source_path).get("screen_size")
    job.resolution_id = resolution_map.get(screen_size) if screen_size else None

    template = Template(profile.description_template or "{{ mediainfo }}")
    rendered = template.render(mediainfo=job.mediainfo_text or "", screenshot_urls=screenshot_urls, notes="")
    # Intestazione in cima e firma in fondo, entrambe facoltative
    # (Configuration > Upload).
    header = settings_repo.get_setting(session, "upload_description_header")
    signature = settings_repo.get_setting(session, "upload_description_signature")
    job.description_rendered = "\n\n".join(part for part in (header, rendered, signature) if part)

    job.status = "ready"
    session.commit()
    return job


def dupe_check(tmdb_id: int, tracker_adapter: TrackerAdapter) -> list[TorrentCandidate]:
    """Passo 7 di docs/SPEC.md §9: mostrato all'utente PRIMA della conferma
    — mai un blocco automatico, procedere comunque resta sempre una
    decisione umana."""
    return tracker_adapter.search_by_tmdb(tmdb_id)


def submit(
    session: Session, job: UploadJob, tracker_adapter: TrackerAdapter, profile: TrackerUploadProfile
) -> UploadJob:
    """Passo 9 di docs/SPEC.md §9 — va chiamato SOLO dopo la conferma umana
    esplicita (docs/SPEC.md: "non negoziabile quanto il recheck forzato del
    reseeding"). app/api/uploads.py è l'unico chiamante previsto."""
    if job.category_id is None or job.type_id is None or job.resolution_id is None or job.tmdb_id is None:
        raise UploadPreparationError("upload_job_incomplete")
    fields = UploadFields(
        name=os.path.basename(job.source_path),
        description=job.description_rendered or "",
        mediainfo=job.mediainfo_text or "",
        category_id=job.category_id,
        type_id=job.type_id,
        resolution_id=job.resolution_id,
        tmdb_id=job.tmdb_id,
        imdb_id=job.imdb_id or "0",
        # Prima di questo fix i due flag del profilo (default_anonymous/
        # default_personal_release, editabili da UI da subito) non venivano
        # mai letti qui: un upload risultava sempre non-anonimo a
        # prescindere da cosa l'utente avesse impostato sul profilo.
        anonymous=profile.default_anonymous,
        personal_release=profile.default_personal_release,
    )
    job.status = "uploading"
    session.commit()
    try:
        torrent_id_remote = tracker_adapter.upload_torrent(fields, job.torrent_path)
    except UploadError as exc:
        job.status = "failed"
        job.error_message = str(exc)
        session.commit()
        raise
    job.status = "uploaded"
    job.torrent_id_remote = torrent_id_remote
    session.commit()
    return job
