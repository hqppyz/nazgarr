from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from app import auth, db, pipeline, review, scheduler, startup_checks
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.disks import router as disks_router
from app.api.full_checks import router as full_checks_router
from app.api.library import router as library_router
from app.api.radarr_instances import router as radarr_instances_router
from app.api.reviews import router as reviews_router
from app.api.runs import router as runs_router
from app.api.schedule import router as schedule_router
from app.api.settings import router as settings_router
from app.api.sonarr_instances import router as sonarr_instances_router
from app.api.system import router as system_router
from app.api.torrent_clients import router as torrent_clients_router
from app.api.torrents import router as torrents_router
from app.api.trackers import router as trackers_router
from app.api.uploads import router as uploads_router
from app.config import load_settings
from app.frontend import mount_frontend
from app.logging_config import add_file_handler, configure_logging
from app.version import __commit__, __version__

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    add_file_handler(Path(settings.data_dir) / "logs")
    db.migrate_legacy_db_filename(settings.data_dir)
    engine = db.make_engine(settings.db_path)
    db.migrate_legacy_media_path_id(engine)
    db.repair_dangling_media_file_legacy_fk(engine)
    db.migrate_legacy_run_log_phase_check(engine)
    db.apply_schema(engine)
    db.migrate_schema(engine)
    session_factory = db.make_session_factory(engine)
    with session_factory() as session:
        startup_checks.verify_secret_key(session)
        pipeline.close_interrupted_runs(session)
        review.reset_interrupted_verifications(session)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.started_at = datetime.now(UTC)

    app.state.scheduler = scheduler.build_scheduler(session_factory, settings.data_dir)
    app.state.scheduler.start()
    try:
        yield
    finally:
        app.state.scheduler.shutdown(wait=False)


app = FastAPI(title="Nazgarr", lifespan=lifespan)

# /api/auth/* è l'unico router mai protetto da require_auth (altrimenti
# nessuno potrebbe mai autenticarsi la prima volta) — vedi app/api/auth.py.
# Le viste della libreria restituiscono JSON da diversi MB (decine di
# migliaia di file): compressi in gzip pesano una frazione in rete.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.include_router(auth_router)

# API JSON pura sotto /api/* fin dall'inizio (docs/SPEC.md §10). Protette da
# require_auth, che però lascia passare tutto finché nessun login è stato
# configurato (app/auth.py) — un'istanza esistente senza login impostato
# continua a funzionare esattamente come prima di questa fase.
_protected = Depends(auth.require_auth)
app.include_router(disks_router, dependencies=[_protected])
app.include_router(runs_router, dependencies=[_protected])
app.include_router(library_router, dependencies=[_protected])
app.include_router(torrent_clients_router, dependencies=[_protected])
app.include_router(settings_router, dependencies=[_protected])
app.include_router(trackers_router, dependencies=[_protected])
app.include_router(radarr_instances_router, dependencies=[_protected])
app.include_router(sonarr_instances_router, dependencies=[_protected])
app.include_router(reviews_router, dependencies=[_protected])
app.include_router(full_checks_router, dependencies=[_protected])
app.include_router(torrents_router, dependencies=[_protected])
app.include_router(schedule_router, dependencies=[_protected])
app.include_router(dashboard_router, dependencies=[_protected])
app.include_router(uploads_router, dependencies=[_protected])
app.include_router(system_router, dependencies=[_protected])


class HealthResponse(BaseModel):
    status: str
    version: str
    commit: str | None = None  # commit dell'immagine, per riconoscere a colpo d'occhio la build in uso


@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", version=__version__, commit=__commit__)


# Sempre per ultimo: il catch-all del frontend (app/frontend.py) non deve
# mai avere la possibilità di intercettare le route /api/* sopra.
mount_frontend(app)
