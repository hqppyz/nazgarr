"""Un tetto alla dimensione del corpo delle richieste (audit 2026-10-18).

FastAPI legge e decodifica tutto il corpo JSON prima di risolvere le
dipendenze, login compreso: senza un tetto chiunque raggiungesse la porta
poteva mandare a /api/auth/login (o a qualunque POST con un corpo) qualche
GB, o un corpo a pezzi senza fine, e far crescere l'unico processo fino
all'OOM killer. Nessuna route riceve file: ogni corpo è un JSON di pochi KB,
e il più grande (un pack di upload_pack.MAX_FILES percorsi) resta sotto i
2 MB anche con percorsi lunghi.

Middleware ASGI puro, il più esterno di tutti (nazgarr/main.py): un
Content-Length oltre il tetto è un 413 subito, senza leggere niente; un
corpo a pezzi (chunked) si conta mentre arriva e si ferma appena lo supera."""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nazgarr.core.errors import coded_detail

MAX_BODY_BYTES = 2 * 1024 * 1024


class BodyTooLarge(HTTPException):
    """Un HTTPException: FastAPI lo lascia passare mentre legge il corpo, e
    diventa il solito errore in JSON."""

    def __init__(self, limit: int):
        super().__init__(status_code=413, detail=coded_detail("request_too_large", limit=limit))


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None  # uvicorn rifiuta già un valore malformato: qui conta il conteggio
    return None


def _too_large(limit: int) -> JSONResponse:
    error = BodyTooLarge(limit)
    return JSONResponse({"detail": error.detail}, status_code=error.status_code)


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            await _too_large(self.max_bytes)(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLarge(self.max_bytes)
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except BodyTooLarge:
            # Di solito il 413 l'ha già mandato FastAPI. Qui arriva solo se il
            # corpo si leggeva fuori da una route: a risposta già partita non
            # resta che chiudere (uvicorn chiude la connessione).
            if not started:
                await _too_large(self.max_bytes)(scope, receive, send)
