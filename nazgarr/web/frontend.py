"""Serve la build statica del frontend (Fase 8, docs/SPEC.md §10-11) dallo
stesso container FastAPI — un solo processo/container, coerente con
CLAUDE.md/SPEC.md §11 ("Vite build, served by the FastAPI container").

Nessun mount se `frontend/dist` non esiste (build non ancora fatta, o
sviluppo backend-only con `pytest`/TestClient) — mai un errore per
un'assenza attesa, solo `/` risponde 404 come qualunque route non
registrata."""

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from nazgarr.core.fs_scope import ScopeViolation, resolve_scoped

# Nel repository (sviluppo, Docker) frontend/dist; nel pacchetto Python la
# sua copia in nazgarr/_assets/web (scripts/build_package.sh).
_PACKAGE = os.path.dirname(os.path.dirname(__file__))
_REPO_DIST = os.path.join(_PACKAGE, "..", "frontend", "dist")
FRONTEND_DIST = _REPO_DIST if os.path.isdir(_REPO_DIST) else os.path.join(_PACKAGE, "_assets", "web")

# Cache del browser (audit 2026-10-18). Senza Cache-Control il browser
# indovinava da Last-Modified (l'ora della build dell'immagine): dopo un
# aggiornamento poteva riusare per giorni l'index.html vecchio, cioè il
# frontend vecchio contro le API nuove, e i chunk che quello chiedeva non
# esistevano più (404, pagina bianca). index.html e gli altri file senza hash
# si riconvalidano sempre (un 304 se non sono cambiati); i file di /assets
# hanno l'hash del contenuto nel nome (Vite) e non cambiano mai.
_REVALIDATE = {"Cache-Control": "no-cache"}
_IMMUTABLE = "public, max-age=31536000, immutable"


class _HashedAssets(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = _IMMUTABLE
        return response


def mount_frontend(app: FastAPI, dist_dir: str = FRONTEND_DIST) -> bool:
    if not os.path.isdir(dist_dir):
        return False

    assets_dir = os.path.join(dist_dir, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", _HashedAssets(directory=assets_dir), name="frontend-assets")

    index_path = os.path.join(dist_dir, "index.html")

    # Catch-all registrato PER ULTIMO (in nazgarr/main.py, dopo ogni
    # app.include_router di /api/*): Starlette fa match delle route
    # nell'ordine in cui sono aggiunte, quindi non intercetta mai /api/* né
    # /openapi.json — già registrate prima di questa.
    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # Un /api/… che non esiste è un 404 in JSON, non la pagina: chi chiama
        # le API (un'altra istanza, il CLI, uno script) deve capire che manca
        # (es. un endpoint di una versione più nuova), non ricevere HTML con 200.
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": {"code": "not_found",
                                                                     "params": {"path": f"/{full_path}"}}})
        # Mai fuori da dist: senza, "/%2e%2e/..." leggeva qualunque file del
        # processo (DB, config.yaml) e questa route non passa dal login.
        try:
            candidate = resolve_scoped(dist_dir, full_path)
        except ScopeViolation:
            return FileResponse(index_path, headers=_REVALIDATE)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate, headers=_REVALIDATE)
        # Route lato client di React Router (es. /reseeding/dashboard):
        # nessun file corrispondente, si serve sempre index.html e ci
        # pensa React Router a risolvere il path reale lato browser.
        return FileResponse(index_path, headers=_REVALIDATE)

    return True
