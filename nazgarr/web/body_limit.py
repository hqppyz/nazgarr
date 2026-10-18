"""Un tetto alla dimensione del corpo delle richieste, e nessun corpo letto
prima delle credenziali (audit 2026-10-18).

FastAPI legge e decodifica tutto il corpo JSON prima di risolvere le
dipendenze, quindi anche prima del 401 di require_auth: senza un tetto
chiunque raggiungesse la porta poteva mandare a /api/auth/login, o a
qualunque POST con un corpo, qualche GB o un corpo a pezzi senza fine, e far
crescere l'unico processo fino all'OOM killer. E anche sotto un tetto di 2 MB
un JSON fatto apposta (`[{},{},...]`) costava oltre 100 MB e quasi un secondo
di loop a richiesta: una decina in parallelo fermava il processo su un NAS
piccolo. Nessuna route riceve file: ogni corpo è un JSON di pochi KB, e il
più grande (un pack di upload_pack.MAX_FILES percorsi) resta sotto i 2 MB
anche con percorsi lunghi.

Quindi, per percorso:
- /api/auth/* (login, creazione dell'account, cambio password): corpi di
  poche centinaia di byte, 16 KB al massimo, per chiunque.
- /api/arr-hooks/*: il webhook di Radarr/Sonarr legge il corpo da sé, dopo
  la sua password e con il suo tetto (nazgarr/api/arr_hooks.py); qui solo i
  2 MB.
- tutto il resto: prima di passare all'app anche un solo byte del corpo, le
  credenziali (lo stesso require_auth della route, nel threadpool); senza,
  l'errore che darebbe la route (401 o 403). Poi 2 MB.

Middleware ASGI puro, il più esterno di tutti (nazgarr/main.py): un
Content-Length oltre il tetto è un 413 subito, senza leggere niente; un corpo
a pezzi (chunked) si conta mentre arriva e si ferma appena lo supera."""

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nazgarr.core.errors import coded_detail
from nazgarr.web import auth

MAX_BODY_BYTES = 2 * 1024 * 1024
LOGIN_BODY_BYTES = 16 * 1024

_LOGIN_PREFIX = "/api/auth/"  # senza credenziali per forza: login e creazione dell'account
_OWN_PASSWORD_PREFIX = "/api/arr-hooks/"  # il corpo si legge dopo la password del webhook


class BodyRefused(HTTPException):
    """Un HTTPException: FastAPI lo lascia passare mentre legge il corpo, e
    diventa il solito errore in JSON."""


def _too_large(limit: int) -> BodyRefused:
    return BodyRefused(status_code=413, detail=coded_detail("request_too_large", limit=limit))


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None  # uvicorn rifiuta già un valore malformato: qui conta il conteggio
    return None


def _check_credentials(scope: Scope) -> BodyRefused | None:
    """None se chi chiama ha un token o una API key validi (require_auth),
    se no l'errore che gli darebbe la route."""
    factory = getattr(getattr(scope.get("app"), "state", None), "session_factory", None)
    if factory is None:  # prima dello startup: nessuno è ancora entrato
        return BodyRefused(status_code=401, detail=coded_detail("auth_required"))
    with factory() as session:
        try:
            auth.require_auth(Request(scope), session)
        except HTTPException as exc:
            return BodyRefused(status_code=exc.status_code, detail=exc.detail, headers=exc.headers)
    return None


def _response(error: BodyRefused) -> JSONResponse:
    return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES, login_bytes: int = LOGIN_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.login_bytes = login_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        login = path.startswith(_LOGIN_PREFIX)
        limit = self.login_bytes if login else self.max_bytes
        must_check = not login and not path.startswith(_OWN_PASSWORD_PREFIX)

        declared = _declared_length(scope)
        refused = _too_large(limit) if declared is not None and declared > limit else None
        if refused is None and must_check and declared:  # un corpo in arrivo: prima le credenziali
            must_check = False
            refused = await run_in_threadpool(_check_credentials, scope)
        if refused is not None:
            await _response(refused)(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received, must_check
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                if body and must_check:  # a pezzi, senza Content-Length
                    must_check = False
                    refused = await run_in_threadpool(_check_credentials, scope)
                    if refused is not None:
                        raise refused
                received += len(body)
                if received > limit:
                    raise _too_large(limit)
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except BodyRefused as error:
            # Di solito la risposta l'ha già mandata FastAPI. Qui arriva solo se
            # il corpo si leggeva fuori da una route: a risposta già partita non
            # resta che chiudere (uvicorn chiude la connessione).
            if not started:
                await _response(error)(scope, receive, send)
