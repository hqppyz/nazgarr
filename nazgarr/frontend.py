"""Serve la build statica del frontend (Fase 8, docs/SPEC.md §10-11) dallo
stesso container FastAPI — un solo processo/container, coerente con
CLAUDE.md/SPEC.md §11 ("Vite build, served by the FastAPI container").

Nessun mount se `frontend/dist` non esiste (build non ancora fatta, o
sviluppo backend-only con `pytest`/TestClient) — mai un errore per
un'assenza attesa, solo `/` risponde 404 come qualunque route non
registrata."""

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from nazgarr.fs_scope import ScopeViolation, resolve_scoped

# Nel repository (sviluppo, Docker) frontend/dist; nel pacchetto Python la
# sua copia in nazgarr/_assets/web (scripts/build_package.sh).
_REPO_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
FRONTEND_DIST = _REPO_DIST if os.path.isdir(_REPO_DIST) else os.path.join(os.path.dirname(__file__), "_assets", "web")


def mount_frontend(app: FastAPI, dist_dir: str = FRONTEND_DIST) -> bool:
    if not os.path.isdir(dist_dir):
        return False

    assets_dir = os.path.join(dist_dir, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    index_path = os.path.join(dist_dir, "index.html")

    # Catch-all registrato PER ULTIMO (in nazgarr/main.py, dopo ogni
    # app.include_router di /api/*): Starlette fa match delle route
    # nell'ordine in cui sono aggiunte, quindi non intercetta mai /api/*,
    # /docs, /redoc, /openapi.json — già tutte registrate prima di questa.
    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # Mai fuori da dist: senza, "/%2e%2e/..." leggeva qualunque file del
        # processo (DB, config.yaml) e questa route non passa dal login.
        try:
            candidate = resolve_scoped(dist_dir, full_path)
        except ScopeViolation:
            return FileResponse(index_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        # Route lato client di React Router (es. /reseeding/dashboard):
        # nessun file corrispondente, si serve sempre index.html e ci
        # pensa React Router a risolvere il path reale lato browser.
        return FileResponse(index_path)

    return True
