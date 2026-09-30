"""Protezioni HTTP comuni a tutta l'app.

- Richieste che cambiano qualcosa (POST, PUT, PATCH, DELETE) che arrivano da
  un altro sito: rifiutate. Il browser lo dice con Sec-Fetch-Site, o con un
  Origin di un host diverso. Con il login obbligatorio e il token
  nell'header un form di un altro sito non passerebbe comunque; questo
  chiude anche i casi che sfuggissero (difesa in profondità contro il CSRF).
  Script e servizi (curl, API key) non mandano Origin: passano.
- Header di sicurezza su ogni risposta: niente iframe altrui
  (clickjacking), niente sniffing del tipo, niente referrer verso altri
  siti, e una Content-Security-Policy che permette script e connessioni
  solo da Nazgarr stesso (un eventuale XSS non può mandare il token altrove).
"""

from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api_errors import coded_detail

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


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in UNSAFE_METHODS and cross_site(request):
            return JSONResponse({"detail": coded_detail("cross_site_request")}, status_code=403)
        response = await call_next(request)
        for name, value in HEADERS.items():
            response.headers.setdefault(name, value)
        return response
