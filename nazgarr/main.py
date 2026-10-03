import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from nazgarr import auth, db, pipeline, review, scheduler, startup_checks, upload_profiles
from nazgarr.api.api_keys import router as api_keys_router
from nazgarr.api.auth import router as auth_router
from nazgarr.api.dashboard import router as dashboard_router
from nazgarr.api.disks import router as disks_router
from nazgarr.api.full_checks import router as full_checks_router
from nazgarr.api.library import router as library_router
from nazgarr.api.metadata import router as metadata_router
from nazgarr.api.plugins import router as plugins_router
from nazgarr.api.radarr_instances import router as radarr_instances_router
from nazgarr.api.reviews import router as reviews_router
from nazgarr.api.runs import router as runs_router
from nazgarr.api.schedule import router as schedule_router
from nazgarr.api.settings import router as settings_router
from nazgarr.api.sonarr_instances import router as sonarr_instances_router
from nazgarr.api.system import router as system_router
from nazgarr.api.torrent_clients import router as torrent_clients_router
from nazgarr.api.torrents import router as torrents_router
from nazgarr.api.trackers import router as trackers_router
from nazgarr.api.uploads import router as uploads_router
from nazgarr.api.webhooks import router as webhooks_router
from nazgarr.config import load_settings
from nazgarr.frontend import mount_frontend
from nazgarr.logging_config import add_file_handler, configure_logging
from nazgarr.plugins import loader as plugin_loader
from nazgarr.security_headers import SecurityMiddleware
from nazgarr.upload_worker import UploadWorker
from nazgarr.version import __commit__, __version__

configure_logging()


logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    # Anche fuori dal container: DB, log e .torrent solo per questo utente.
    os.umask(0o077)
    add_file_handler(Path(settings.data_dir) / "logs")
    # Prima di tutto il resto: gli adapter dei plugin servono già allo startup.
    plugin_loader.load(settings.data_dir)
    db.migrate_legacy_db_filename(settings.data_dir)
    engine = db.make_engine(settings.db_path)
    db.migrate_legacy_media_path_id(engine)
    db.repair_dangling_media_file_legacy_fk(engine)
    db.migrate_legacy_run_log_phase_check(engine)
    db.migrate_legacy_upload_job(engine)
    db.apply_schema(engine)
    db.migrate_schema(engine)
    db.migrate_disk_folders(engine)
    db.encrypt_plaintext_secrets(engine)
    session_factory = db.make_session_factory(engine)
    with session_factory() as session:
        startup_checks.verify_secret_key(session)
        # Senza account: tutto chiuso finché non lo si crea con questo codice.
        app.state.setup_code = None
        if not auth.is_auth_configured(session):
            app.state.setup_code = auth.new_setup_code()
            logger.warning(
                "\n%s\nNo account yet: open Nazgarr and create it with this setup code: %s\n%s",
                "=" * 72, app.state.setup_code, "=" * 72,
            )
        pipeline.close_interrupted_runs(session)
        review.reset_interrupted_verifications(session)
        upload_profiles.sync_tracker_languages(session)
        upload_profiles.sync_naming_rules(session)
        upload_profiles.sync_description_templates(session)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.started_at = datetime.now(UTC)

    app.state.scheduler = scheduler.build_scheduler(session_factory, settings.data_dir)
    app.state.scheduler.start()
    app.state.upload_worker = UploadWorker(session_factory, settings.data_dir)
    app.state.upload_worker.resume()
    scheduler.add_watch_job(app.state.scheduler, session_factory, app.state.upload_worker)
    try:
        yield
    finally:
        app.state.scheduler.shutdown(wait=False)
        app.state.upload_worker.shutdown()


app = FastAPI(title="Nazgarr", lifespan=lifespan)

# /api/auth/* è l'unico router mai protetto da require_auth (altrimenti
# nessuno potrebbe mai autenticarsi la prima volta) — vedi nazgarr/api/auth.py.
# Le viste della libreria restituiscono JSON da diversi MB (decine di
# migliaia di file): compressi in gzip pesano una frazione in rete.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(SecurityMiddleware)
app.include_router(auth_router)

# API JSON pura sotto /api/* fin dall'inizio (docs/SPEC.md §10). Protette da
# require_auth, che però lascia passare tutto finché nessun login è stato
# configurato (nazgarr/auth.py) — un'istanza esistente senza login impostato
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
app.include_router(metadata_router, dependencies=[_protected])
app.include_router(system_router, dependencies=[_protected])
app.include_router(plugins_router, dependencies=[_protected])
app.include_router(webhooks_router, dependencies=[_protected])
# Le API key si gestiscono solo con il login, mai con un'altra API key.
app.include_router(api_keys_router, dependencies=[Depends(auth.require_login)])


class HealthResponse(BaseModel):
    status: str
    version: str
    commit: str | None = None  # commit dell'immagine, per riconoscere a colpo d'occhio la build in uso


@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", version=__version__, commit=__commit__)


# Sempre per ultimo: il catch-all del frontend (nazgarr/frontend.py) non deve
# mai avere la possibilità di intercettare le route /api/* sopra.
mount_frontend(app)
