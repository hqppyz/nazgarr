"""Base per le eccezioni di dominio mostrate all'utente: un codice stabile
+ parametri, mai un messaggio italiano libero che arriva al client. Ogni
endpoint che cattura una sottoclasse la traduce in
HTTPException(detail={"code": exc.code, "params": exc.params}) — il
frontend risolve il codice in inglese via t('errors.' + code, params)
(frontend/src/lib/i18n.ts, locales/en/errors.ts, stessi codici)."""


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
