"""Pezzi del modulo Upload condivisi fra i passi del flusso v2 (docs/SPEC.md
§9): la mappa dai segnali guessit al type_id del profilo e la descrizione
dal template del tracker. L'orchestrazione dei passi vive in
nazgarr/upload/jobs.py e nazgarr/upload/worker.py. Dominio separato dal reseeding:
non tocca mai media_item/candidate/match_review/seed_job."""

import logging

from jinja2 import TemplateError
from jinja2.sandbox import ImmutableSandboxedEnvironment, SecurityError
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


# Quanto può crescere un numero o un testo dentro un template (audit
# 2026-10-18): la sandbox ferma il codice, non i conti. 9**(9**8) teneva il
# GIL per ore (tutto il processo fermo, API e scheduler compresi), e
# 'x' * 10**10 chiedeva 10 GB in un colpo.
MAX_INT_BITS = 64 * 1024
MAX_SEQUENCE = 1_000_000


def _too_big_power(left, right) -> bool:
    if isinstance(right, (int, float)) and abs(right) > 10_000:
        return True
    return isinstance(left, int) and isinstance(right, int) and right > 0 and left.bit_length() * right > MAX_INT_BITS


def _too_big_product(left, right) -> bool:
    if isinstance(left, int) and isinstance(right, int):
        return left.bit_length() + right.bit_length() > MAX_INT_BITS
    for sequence, times in ((left, right), (right, left)):
        if isinstance(sequence, (str, list, tuple)) and isinstance(times, int) and len(sequence) * times > MAX_SEQUENCE:
            return True
    return False


class _DescriptionTemplates(ImmutableSandboxedEnvironment):
    """La sandbox, con ** e * controllati prima di calcolarli (come
    suggerisce la documentazione di Jinja): intercettarli spegne anche il
    calcolo dei valori costanti quando il template si compila, che
    avveniva prima di qualsiasi controllo."""

    intercepted_binops = frozenset({"**", "*"})

    def call_binop(self, context, operator, left, right):
        if (operator == "**" and _too_big_power(left, right)) or (operator == "*" and _too_big_product(left, right)):
            raise SecurityError(f"the result of {operator} would be too large")
        return super().call_binop(context, operator, left, right)


# Il template lo scrive l'utente (profilo di upload del tracker): sempre in
# una sandbox, mai jinja2.Template, che permetterebbe di eseguire codice sul
# server con {{ cycler.__init__.__globals__.os... }}. Nessun escaping HTML: è
# BBCode, non una pagina.
_TEMPLATES = _DescriptionTemplates(autoescape=False)


class DescriptionTemplateError(CodedError):
    """Il template della descrizione non si può usare (sintassi, o qualcosa
    che la sandbox non permette)."""


def render_template(source: str, **values) -> str:
    try:
        return _TEMPLATES.from_string(source).render(**values)
    except TemplateError as exc:  # SecurityError compresa
        raise DescriptionTemplateError("upload_description_template_invalid", error=str(exc)) from exc
    except (ArithmeticError, TypeError, ValueError, MemoryError, RecursionError) as exc:
        # Un conto del template che non si può fare ({{ 1/0 }}, un numero da
        # più di 4300 cifre da scrivere): lo stesso errore, con il suo codice.
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
