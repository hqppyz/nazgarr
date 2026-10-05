"""Pezzi del modulo Upload condivisi fra i passi del flusso v2 (docs/SPEC.md
§9): la mappa dai segnali guessit al type_id del profilo e la descrizione
dal template del tracker. L'orchestrazione dei passi vive in
nazgarr/upload/jobs.py e nazgarr/upload/worker.py. Dominio separato dal reseeding:
non tocca mai media_item/candidate/match_review/seed_job."""

import logging

from jinja2 import TemplateError
from jinja2.sandbox import ImmutableSandboxedEnvironment
from sqlalchemy.orm import Session

from nazgarr.core import settings_repo
from nazgarr.core.errors import CodedError
from nazgarr.core.models import TrackerUploadProfile
from nazgarr.core.version import __version__

logger = logging.getLogger(__name__)

# Mapping da segnali guessit a chiavi type_id — euristica best-effort,
# MAI la fonte di verità: category_id/resolution_id si ricavano in modo
# affidabile (content_type risolto, screen_size di guessit combacia quasi
# sempre con le chiavi resolution_id_map), ma la distinzione
PROJECT_URL = "https://github.com/lktorrentz/nazgarr"
# Servito da GitHub (repo pubblico): il tracker non vede mai l'istanza.
CREDIT_LOGO_URL = "https://raw.githubusercontent.com/lktorrentz/nazgarr/main/docs/assets/nazgarr-credit.png"


def credit_line() -> str:
    """La riga sempre in fondo a ogni descrizione, dopo la firma dell'utente:
    centrata, staccata da quello che c'è sopra (render_description)."""
    return (
        f"[center][url={PROJECT_URL}][img=16]{CREDIT_LOGO_URL}[/img][/url] "
        f"[size=14]Uploaded with [url={PROJECT_URL}]Nazgarr[/url] v{__version__}[/size][/center]"
    )


# Il template lo scrive l'utente (profilo di upload del tracker): sempre in
# una sandbox, mai jinja2.Template, che permetterebbe di eseguire codice sul
# server con {{ cycler.__init__.__globals__.os... }}. Nessun escaping HTML: è
# BBCode, non una pagina.
_TEMPLATES = ImmutableSandboxedEnvironment(autoescape=False)


class DescriptionTemplateError(CodedError):
    """Il template della descrizione non si può usare (sintassi, o qualcosa
    che la sandbox non permette)."""


def render_template(source: str, **values) -> str:
    try:
        return _TEMPLATES.from_string(source).render(**values)
    except TemplateError as exc:  # SecurityError compresa
        raise DescriptionTemplateError("upload_description_template_invalid", error=str(exc)) from exc


def render_description(
    session: Session, profile: TrackerUploadProfile, mediainfo: str, screenshot_urls: list[str], notes: str = ""
) -> str:
    """Il template Jinja2 del profilo, con l'intestazione in cima e la firma
    in fondo, entrambe facoltative (Configuration > Upload), e per ultima la
    riga di Nazgarr (credit_line), sempre."""
    rendered = render_template(
        profile.description_template or "{{ mediainfo }}",
        mediainfo=mediainfo or "", screenshot_urls=screenshot_urls, notes=notes,
    )
    header = settings_repo.get_setting(session, "upload_description_header")
    signature = settings_repo.get_setting(session, "upload_description_signature")
    body = "\n\n".join(part for part in (header, rendered, signature) if part)
    # Una riga vuota in più prima dei crediti: staccati dal resto.
    return f"{body}\n\n\n{credit_line()}"
