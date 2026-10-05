"""Base per le eccezioni di dominio mostrate all'utente: un codice stabile
+ parametri, mai un messaggio italiano libero che arriva al client. Ogni
endpoint che cattura una sottoclasse la traduce in
HTTPException(detail={"code": exc.code, "params": exc.params}) — il
frontend risolve il codice in inglese via t('errors.' + code, params)
(frontend/src/lib/i18n.ts, locales/en/errors.ts, stessi codici).

english() fa lo stesso lato server, per un testo che resta salvato (l'errore
di un reseed) o stampato dalla CLI: i messaggi inglesi del frontend,
esportati in nazgarr/cli_client/messages_en.json (scripts/export_cli_messages.py)."""

import json
from collections import defaultdict
from functools import cache
from importlib import resources


class CodedError(Exception):
    def __init__(self, code: str, **params):
        self.code = code
        self.params = params
        super().__init__(code)


def coded_detail(code: str, **params) -> dict:
    """Forma di HTTPException(detail=...) per un errore autorato direttamente
    nel layer API (non una CodedError catturata altrove) — stessa forma,
    {"code", "params"}, per un solo formato riconosciuto dal frontend."""
    return {"code": code, "params": params}


def from_coded_error(exc: CodedError) -> dict:
    return {"code": exc.code, "params": exc.params}


@cache
def _english_messages() -> dict[str, str]:
    return json.loads(resources.files("nazgarr.cli_client").joinpath("messages_en.json").read_text())


def english(code: str, params: dict | None = None) -> str:
    """Il messaggio inglese di un codice, con i parametri; il codice stesso
    (con i parametri) se non è nel catalogo."""
    template = _english_messages().get(code)
    if template is None:
        details = ", ".join(f"{k}={v}" for k, v in (params or {}).items())
        return code + (f" ({details})" if details else "")
    return template.format_map(defaultdict(lambda: "?", dict(params or {})))
