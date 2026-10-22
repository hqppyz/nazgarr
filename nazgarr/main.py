import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr import scheduler
from nazgarr.api.api_keys import router as api_keys_router
from nazgarr.api.arr_hooks import router as arr_hooks_router
from nazgarr.api.auth import router as auth_router
from nazgarr.api.dashboard import router as dashboard_router
from nazgarr.api.disks import router as disks_router
from nazgarr.api.full_checks import router as full_checks_router
from nazgarr.api.instances import remote_router
from nazgarr.api.instances import router as instances_router
from nazgarr.api.library import router as library_router
from nazgarr.api.metadata import router as metadata_router
from nazgarr.api.notifications import router as notifications_router
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
from nazgarr.core import db, db_startup, instance_lock, startup_checks, updates
from nazgarr.core.config import load_settings
from nazgarr.core.logs import add_file_handler, configure_logging
from nazgarr.core.version import __commit__, __version__
from nazgarr.plugins import loader as plugin_loader
from nazgarr.plugins import switch as plugin_switch
from nazgarr.reseed import pipeline, review
from nazgarr.upload import profiles as upload_profiles
from nazgarr.upload.worker import UploadWorker
from nazgarr.web import auth
from nazgarr.web.body_limit import BodyLimitMiddleware
from nazgarr.web.deps import get_session
from nazgarr.web.frontend import mount_frontend
from nazgarr.web.recovery import RecoveryMiddleware
from nazgarr.web.security_headers import SecurityMiddleware

configure_logging()


logger = logging.getLogger(__name__)


def _keep_private(*paths_and_modes: tuple[str, int]) -> None:
    """DB, log e .torrent (con le passkey negli announce) solo per l'utente
    dell'app, anche fuori dal container. Prima lo faceva una umask 077 su
    tutto il processo, che però valeva anche per le cartelle create sui dischi
    dei media: nascevano 0700, e un client torrent con un altro utente non ci
    entrava (audit 2026-10-18). Ora i permessi stretti stanno solo dove ci
    sono i segreti: la cartella dei dati (tutto quello che c'è dentro resta
    privato, qualunque sia il modo dei file) e il database."""
    for path, mode in paths_and_modes:
        if not os.path.exists(path):
            continue
        try:
            os.chmod(path, mode)
        except OSError as exc:
            logger.warning("Impossibile rendere %s privato (%o): %s", path, mode, exc)


def _start(app: FastAPI, settings, outcome: db_startup.Outcome) -> None:
    """Il database è aggiornato: i controlli dell'avvio, poi scheduler e
    worker degli upload."""
    engine = outcome.engine
    # SQLite dà a -wal e -shm i permessi del database quando li ricrea.
    _keep_private(*((settings.db_path + suffix, 0o600) for suffix in ("", "-wal", "-shm")))
    session_factory = db.make_session_factory(engine)
    with session_factory() as session:
        db_startup.record_backup(session, outcome)  # per Impostazioni › Applicazione
        plugin_switch.apply_disabled(session)  # i plugin spenti dall'utente, inclusi o installati
        updates.init_seen(session)  # un'installazione nuova non mostra note di versioni mai usate
        startup_checks.verify_secret_key(session)
        auth.token_audience(session)  # il claim "aud" dei token, prima di qualunque richiesta
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
    app.state.engine = engine
    app.state.session_factory = session_factory

    app.state.scheduler = scheduler.build_scheduler(session_factory, settings.data_dir)
    app.state.scheduler.start()
    app.state.upload_worker = UploadWorker(session_factory, settings.data_dir)
    app.state.upload_worker.resume()
    scheduler.add_watch_job(app.state.scheduler, session_factory, app.state.upload_worker)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    os.makedirs(settings.data_dir, mode=0o700, exist_ok=True)
    _keep_private((settings.data_dir, 0o700))
    add_file_handler(Path(settings.data_dir) / "logs")
    # Prima di tutto il resto: gli adapter dei plugin servono già allo startup.
    plugin_loader.load(settings.data_dir)
    app.state.settings = settings
    app.state.started_at = datetime.now(UTC)
    app.state.recovery = None
    # Il lucchetto di chi usa il DB: `nazgarr db restore` non lo sostituisce
    # sotto i piedi del server (nazgarr/core/instance_lock.py).
    lock = instance_lock.acquire(settings.data_dir)
    if lock is None:
        logger.warning("Another Nazgarr process seems to use %s: run only one per data folder", settings.data_dir)
    try:
        # Backup se l'aggiornamento cambierà qualcosa, poi schema, colonne
        # nuove e passi una tantum (nazgarr/core/db_startup.py, migrations.py).
        outcome = db_startup.prepare(settings)
        if outcome.failed:
            # Modalità di ripristino: niente scheduler, worker, plugin o route
            # che toccano il DB, solo la pagina che dice cosa fare
            # (nazgarr/web/recovery.py). Il lucchetto si lascia: il DB è
            # libero per `nazgarr db restore`, anche con il container acceso.
            app.state.recovery = outcome.status
            if lock is not None:
                lock.release()
            try:
                yield
            finally:
                app.state.recovery = None
            return
        _start(app, settings, outcome)
        try:
            yield
        finally:
            app.state.scheduler.shutdown(wait=False)
            app.state.upload_worker.shutdown()
    finally:
        if lock is not None:
            lock.release()


# Niente /docs e /redoc: caricano Swagger UI e ReDoc da un CDN con uno script
# inline, che la CSP dell'app (nazgarr/web/security_headers.py) blocca, quindi
# nel browser erano pagine vuote. Lo schema resta in /openapi.json (audit
# 2026-10-18).
app = FastAPI(title="Nazgarr", lifespan=lifespan, docs_url=None, redoc_url=None)

_MAX_VALIDATION_ERRORS = 50


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Il 422 di FastAPI, ma senza "input" e "ctx": quello di default rimandava
    indietro il valore sbagliato, cioè anche un corpo intero, passato da
    jsonable_encoder sul loop. Con un corpo di 2 MB fatto apposta, prima del
    login, era quasi un secondo di loop e oltre 100 MB a richiesta (audit
    2026-10-18). Tipo, posizione e messaggio bastano all'interfaccia e al CLI;
    oltre i primi 50 errori nessuno legge."""
    errors = [{"type": error["type"], "loc": error["loc"], "msg": error["msg"]}
              for error in exc.errors()[:_MAX_VALIDATION_ERRORS]]
    return JSONResponse(status_code=422, content={"detail": errors})


# Fuori da require_auth ci sono solo due router: /api/auth/* (altrimenti
# nessuno potrebbe mai autenticarsi la prima volta, nazgarr/api/auth.py) e i
# webhook di Radarr/Sonarr (/api/arr-hooks/*), che accettano solo la password
# del webhook di un'istanza (nazgarr/api/arr_hooks.py). Più /api/health, che
# senza credenziali risponde solo "ok".

# Le viste della libreria restituiscono JSON da diversi MB (decine di
# migliaia di file): compressi in gzip pesano una frazione in rete. Livello 6,
# non il 9 di Starlette: su 3,7 MB 15 ms invece di 54, per un file appena più
# grande (audit 2026-10-18).
# La modalità di ripristino (l'aggiornamento del DB non è riuscito) per
# prima, cioè la più interna: le richieste si fermano lì prima di qualunque
# route, con gli header di sicurezza delle altre (nazgarr/web/recovery.py).
app.add_middleware(RecoveryMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
app.add_middleware(SecurityMiddleware)
# Per ultimo, quindi il più esterno: un corpo troppo grande si ferma prima di
# qualunque altra cosa, login compreso, e fuori da /api/auth/* nessun corpo
# passa prima delle credenziali (nazgarr/web/body_limit.py).
app.add_middleware(BodyLimitMiddleware)
app.include_router(auth_router)
# I webhook di Radarr/Sonarr: fuori dal login, con la password del webhook di
# ogni istanza (nazgarr/api/arr_hooks.py).
app.include_router(arr_hooks_router)

# API JSON pura sotto /api/* fin dall'inizio (docs/SPEC.md §10). Protette da
# require_auth: il login è obbligatorio, e finché l'account non esiste tutto
# resta chiuso tranne /api/auth/* (nazgarr/web/auth.py); i webhook di
# Radarr/Sonarr qui sopra accettano solo la password del webhook di un'istanza.
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
app.include_router(notifications_router, dependencies=[_protected])
# Le API key si gestiscono solo con il login, mai con un'altra API key.
app.include_router(api_keys_router, dependencies=[Depends(auth.require_login)])
# Le altre istanze e il proxy verso di loro: solo con il login, mai con una API
# key di questa istanza (nazgarr/api/instances.py).
app.include_router(instances_router, dependencies=[Depends(auth.require_login)])
app.include_router(remote_router, dependencies=[Depends(auth.require_login)])


class HealthResponse(BaseModel):
    status: str
    # Versione e commit dell'immagine, per riconoscere a colpo d'occhio la build
    # in uso: solo a chi è entrato (login o API key). A un visitatore anonimo
    # direbbero quale build attaccare (audit 2026-10-18).
    version: str | None = None
    commit: str | None = None


@app.get("/api/health", response_model=HealthResponse)
def health(request: Request, session: Session = Depends(get_session)):
    """Senza login: l'HEALTHCHECK del container (Dockerfile) ha solo bisogno
    di una risposta, e senza credenziali non legge nemmeno il DB."""
    if auth.optional_identity(request, session) is None:
        return HealthResponse(status="ok")
    return HealthResponse(status="ok", version=__version__, commit=__commit__)


# Sempre per ultimo: il catch-all del frontend (nazgarr/web/frontend.py) non deve
# mai avere la possibilità di intercettare le route /api/* sopra.
mount_frontend(app)
