"""Pezzi del modulo Upload condivisi fra i passi del flusso v2 (docs/SPEC.md
§9): la mappa dai segnali guessit al type_id del profilo e la descrizione
dal template del tracker. L'orchestrazione dei passi vive in
app/upload_jobs.py e app/upload_worker.py. Dominio separato dal reseeding:
non tocca mai media_item/candidate/match_review/seed_job."""

import logging

import guessit
from jinja2 import Template
from sqlalchemy.orm import Session

from app import settings_repo
from app.api_errors import CodedError
from app.models import TrackerUploadProfile

logger = logging.getLogger(__name__)

# Mapping da segnali guessit a chiavi type_id — euristica best-effort,
# MAI la fonte di verità: category_id/resolution_id si ricavano in modo
# affidabile (content_type risolto, screen_size di guessit combacia quasi
# sempre con le chiavi resolution_id_map), ma la distinzione
# REMUX/ENCODE/WEBDL/BDMUX/ecc. dipende da convenzioni di release troppo
# sfumate per un guess automatico affidabile — per questo type_id resta
# sempre modificabile prima dell'approvazione (docs/SPEC.md §9: "risolti,
# modificabili prima dell'invio"), mai bloccante di per sé.
_DEFAULT_TYPE_GUESS = "ENCODE"


class UploadPreparationError(CodedError):
    """Errore non recuperabile prima ancora di provare l'invio — es. tracker
    senza announce_url configurato, o senza un profilo di upload."""


def guess_release_type_key(source_path: str, type_map: dict) -> str | None:
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


def render_description(
    session: Session, profile: TrackerUploadProfile, mediainfo: str, screenshot_urls: list[str], notes: str = ""
) -> str:
    """Il template Jinja2 del profilo, con l'intestazione in cima e la firma
    in fondo, entrambe facoltative (Configuration > Upload)."""
    template = Template(profile.description_template or "{{ mediainfo }}")
    rendered = template.render(mediainfo=mediainfo or "", screenshot_urls=screenshot_urls, notes=notes)
    header = settings_repo.get_setting(session, "upload_description_header")
    signature = settings_repo.get_setting(session, "upload_description_signature")
    return "\n\n".join(part for part in (header, rendered, signature) if part)
