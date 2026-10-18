"""Protezioni HTTP comuni a tutta l'app.

- Richieste che cambiano qualcosa (POST, PUT, PATCH, DELETE) che arrivano da
  un altro sito: rifiutate. Il browser lo dice con Sec-Fetch-Site, o con un
  Origin di un host diverso. Con il login obbligatorio e il token
  nell'header un form di un altro sito non passerebbe comunque; questo
  chiude anche i casi che sfuggissero (difesa in profondità contro il CSRF).
  Script e servizi (curl, API key) non mandano Origin: passano.
- Header di sicurezza su ogni risposta: niente iframe altrui
  (clickjacking), niente sniffing del tipo, niente referrer verso altri
  siti, e una Content-Security-Policy che permette script solo da Nazgarr
  stesso (niente inline, niente plugin, niente <base> altrui) e fetch, XHR e
  WebSocket solo verso Nazgarr. Non è una garanzia che uno script iniettato
  non possa portare fuori il token: le immagini arrivano anche da altri host
  (img-src https:) e nessuna CSP limita la navigazione. Rende difficile far
  girare lo script, non lo ferma una volta partito (audit 2026-10-18).
"""

from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nazgarr.core.errors import coded_detail

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Immagini anche da fuori (poster TMDB, icone, anteprime degli screenshot);
# stili inline per la UI (Tailwind/shadcn); tutto il resto solo da qui.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
)
HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": CSP,
}


def cross_site(request: Request) -> bool:
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site == "cross-site"
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return origin == "null"
    host = request.headers.get("host", "")
    return urlsplit(origin).netloc.lower() != host.lower()


class SecurityMiddleware:
    """Middleware ASGI puro, non BaseHTTPMiddleware: quello passa ogni lettura
    del corpo da un task group, e un errore lì (il 413 di
    nazgarr/web/body_limit.py) arrivava a FastAPI dentro un ExceptionGroup,
    cioè come un 400 qualunque."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        request = Request(scope)
        if request.method in UNSAFE_METHODS and cross_site(request):
            response = JSONResponse({"detail": coded_detail("cross_site_request")}, status_code=403)
            await response(scope, receive, send_with_headers)
            return
        await self.app(scope, receive, send_with_headers)
