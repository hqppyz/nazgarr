"""Scheduler in-process per le run schedulate (docs/SPEC.md §8, Fase 5).

Un solo job APScheduler ('scheduled_run'), il cui trigger cron viene letto
da app_settings alla chiave 'schedule_cron' all'avvio e può essere
riconfigurato a runtime senza restart — coerente con la regola di
configurazione dinamica di docs/SPEC.md §4 (tutto ciò che non è
disk_scan_root/data_dir vive nel DB, editabile da UI). Nessun cron
configurato = nessun job aggiunto, mai un default implicito.

BackgroundScheduler (thread proprio), non AsyncIOScheduler: il lavoro
vero (pipeline.run_bulk_import) è sincrono/bloccante (I/O filesystem,
richieste HTTP sincrone via httpx.Client) — lo stesso motivo per cui il
trigger manuale (nazgarr/api/runs.py) usa BackgroundTasks di FastAPI invece
di una coroutine.
"""

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session, sessionmaker

from nazgarr.core import settings_repo
from nazgarr.core.db_utils import as_utc
from nazgarr.core.models import RunLog
from nazgarr.reseed import exclusive, pipeline, review

logger = logging.getLogger(__name__)

JOB_ID = "scheduled_run"
SETTING_KEY = "schedule_cron"
# Fin dove le ore del cron sono già servite, in ISO UTC: quando è scattata
# l'ultima (anche se poi ha trovato una run in corso e l'ha saltata), o
# quando il cron è stato impostato. Stato interno (settings_registry.MANAGED_KEYS).
LAST_SLOT_KEY = "schedule_last_slot"
# Un'ora persa con Nazgarr fermo o in riavvio: una scansione all'avvio, poco
# dopo, così la lifespan e il worker degli upload partono prima.
CATCH_UP_JOB_ID = "scheduled_run_catch_up"
CATCH_UP_DELAY_SECONDS = 60


def _record_slot(session: Session, when: datetime | None = None) -> None:
    """Le ore fino a `when` (adesso) sono servite. Un errore del DB qui non
    deve fermare la scansione: al più, al prossimo avvio, un recupero in più."""
    try:
        settings_repo.set_setting(session, LAST_SLOT_KEY, (when or datetime.now(UTC)).isoformat())
    except Exception:
        session.rollback()
        logger.warning("Ora dell'ultima scansione pianificata non salvata", exc_info=True)


def _slot_reference(session: Session) -> datetime | None:
    """Da dove contare le ore perse: la chiave, o (un'installazione di prima
    della chiave) l'inizio dell'ultima run pianificata. None se nessuno dei due."""
    raw = settings_repo.get_setting(session, LAST_SLOT_KEY)
    if raw:
        try:
            when = datetime.fromisoformat(raw)
        except ValueError:
            when = None
        if when is not None:
            return as_utc(when)
    row = (session.query(RunLog.started_at).filter(RunLog.run_type == "scheduled")
           .order_by(RunLog.started_at.desc()).first())
    if row is None or row[0] is None:
        return None
    return as_utc(row[0])


def missed_slot(session: Session, cron_expr: str, now: datetime | None = None) -> datetime | None:
    """La prima ora del cron dopo l'ultima servita e non oltre adesso: è
    passata mentre Nazgarr era fermo. None se nessuna, se non c'è un
    riferimento o se il cron non si legge."""
    reference = _slot_reference(session)
    if reference is None:
        return None
    try:
        trigger = CronTrigger.from_crontab(cron_expr)
    except ValueError:
        return None
    slot = trigger.get_next_fire_time(None, reference + timedelta(microseconds=1))
    return slot if slot is not None and slot <= (now or datetime.now(UTC)) else None


def _run_scheduled(session_factory: sessionmaker, data_dir: str) -> None:
    session = session_factory()
    try:
        _record_slot(session)
        try:
            run = pipeline.try_start_run(session, run_type="scheduled")
        except pipeline.RunInProgressError:
            logger.info("Run schedulata saltata: ce n'è già una in corso")
            return
        pipeline.run_bulk_import(session, run, data_dir)
    except Exception:
        # Non deve mai far morire il thread dello scheduler: un ciclo
        # fallito non deve impedire il prossimo (docs/ROADMAP.md Fase 5,
        # "diverse esecuzioni consecutive senza intervento manuale").
        logger.exception("Run schedulata fallita")
    finally:
        session.close()


def _catch_up(session_factory: sessionmaker, data_dir: str) -> None:
    """Il recupero all'avvio (decisione dell'utente, 2026-10-18): si
    ricontrolla prima di partire, col cron di adesso, perché nel frattempo
    l'ora può essere scattata da sola o il cron cambiato (reschedule sposta
    il riferimento). Poi è una scansione pianificata come le altre: lo
    stesso lock (pipeline.try_start_run), saltata se una run è in corso."""
    with session_factory() as session:
        cron_expr = settings_repo.get_setting(session, SETTING_KEY)
        slot = missed_slot(session, cron_expr) if cron_expr else None
    if slot is None:
        logger.info("Recupero della scansione pianificata non più necessario")
        return
    logger.info("Scansione pianificata delle %s persa mentre Nazgarr era fermo: parte adesso", slot.isoformat())
    _run_scheduled(session_factory, data_dir)


def _plan_catch_up(scheduler: BackgroundScheduler, session_factory: sessionmaker, data_dir: str,
                   cron_expr: str) -> None:
    """All'avvio: se un'ora del cron è passata con Nazgarr fermo (spento, in
    riavvio, aggiornato) dall'ultima servita, una scansione sola, anche se
    ne ha perse più d'una. Senza un riferimento (la prima volta, o un DB di
    prima) se ne fissa uno adesso, e nessun recupero: da qui in poi si sa."""
    now = datetime.now(UTC)
    try:
        with session_factory() as session:
            if _slot_reference(session) is None:
                _record_slot(session, now)
                return
            slot = missed_slot(session, cron_expr, now)
    except Exception:
        # Un recupero in meno, mai un avvio fermato.
        logger.exception("Controllo delle scansioni pianificate perse non riuscito")
        return
    if slot is None:
        return
    logger.warning("Scansione pianificata delle %s persa mentre Nazgarr era fermo: parte una volta fra %d s",
                   slot.isoformat(), CATCH_UP_DELAY_SECONDS)
    scheduler.add_job(
        _catch_up, DateTrigger(run_date=now + timedelta(seconds=CATCH_UP_DELAY_SECONDS)),
        args=[session_factory, data_dir], id=CATCH_UP_JOB_ID, replace_existing=True, max_instances=1,
        misfire_grace_time=None,
    )


# Un'ora del cron passata mentre il processo era fermo (l'host in sospensione,
# docker pause, una VM congelata): APScheduler la scarta se il ritardo supera
# misfire_grace_time, di default 1 secondo, e la scansione del giorno saltava
# fino al giorno dopo. None: un'ora persa gira una volta al risveglio (con
# coalesce, una sola anche se ne ha perse più d'una; audit 2026-10-18).
# Un riavvio a cavallo dell'ora (i job vivono in memoria) lo recupera
# _plan_catch_up all'avvio, col riferimento salvato in LAST_SLOT_KEY.
_JOB_DEFAULTS = {"misfire_grace_time": None}


def _add_job(scheduler: BackgroundScheduler, cron_expr: str, session_factory: sessionmaker, data_dir: str) -> None:
    scheduler.add_job(
        _run_scheduled,
        CronTrigger.from_crontab(cron_expr),
        args=[session_factory, data_dir],
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )


RECONCILE_JOB_ID = "reconcile_seed_jobs"
# Consegne di webhook e notifiche (nazgarr/integrations/webhooks.py): spesso, costa una query.
EVENTS_JOB_ID = "deliver_events"
EVENTS_INTERVAL_SECONDS = 15
RECONCILE_INTERVAL_SECONDS = 120


def _reconcile_between_runs(session_factory: sessionmaker) -> None:
    """Esito dei recheck fra una run e l'altra: senza, un seed approvato a
    mano restava "pending" fino alla run successiva, anche col torrent già
    in seed. Solo se c'è qualcosa in attesa, ed è lavoro a lato
    (nazgarr/reseed/exclusive.py, audit 2026-10-18): mai insieme a una run
    (che fa già il suo reconcile alla fine), a "Controlla ora" o
    all'eliminazione di un'esecuzione. Prima guardava solo che nessuna run
    fosse in corso, e lo stesso seed job si riconciliava in due sessioni:
    avvii e arresti doppi nel client, due eventi seed_job.finished. Se è
    occupato, si riprova al giro dopo."""
    session = session_factory()
    try:
        if not review.has_pending_seed_jobs(session):
            return
        with exclusive.side_work(session, holder="seed_jobs"):
            review.reconcile_pending_seed_jobs(session)
    except exclusive.Busy:
        logger.debug("Reconcile periodico dei seed_job rimandato: una run o altro lavoro in corso")
    except Exception:
        logger.exception("Reconcile periodico dei seed_job fallito")
    finally:
        session.close()


def _deliver_events(session_factory: sessionmaker) -> None:
    from nazgarr.integrations import webhooks

    session = session_factory()
    try:
        webhooks.deliver_due(session)
    except Exception:
        logger.exception("Consegna degli eventi fallita")
    finally:
        session.close()


ARR_HOOKS_JOB_ID = "arr_webhook_events"
ARR_HOOKS_INTERVAL_SECONDS = 15


def _apply_arr_webhook_events(session_factory: sessionmaker, data_dir: str) -> None:
    """Gli eventi dei webhook di Radarr/Sonarr in coda (nazgarr/integrations/arr_webhooks.py)."""
    from nazgarr.integrations import arr_webhooks

    session = session_factory()
    try:
        arr_webhooks.process_pending(session, data_dir=data_dir)
    except Exception:
        logger.exception("Eventi dei webhook di Radarr/Sonarr non applicati")
    finally:
        session.close()


HELD_SEEDS_JOB_ID = "upload_held_seeds"
HELD_SEEDS_INTERVAL_SECONDS = 30


def _reconcile_held_seeds(session_factory: sessionmaker, data_dir: str) -> None:
    """I torrent aggiunti fermi dal flusso degli upload (i reseed, "Riprova il
    seed"): partono quando il loro recheck è riuscito (decisione dell'utente,
    2026-10-19; nazgarr/upload/execute.py::reconcile_held_seeds). Una query
    se non c'è niente in attesa; anche durante una run, che non tocca gli
    upload."""
    from nazgarr.upload import execute as upload_execute

    session = session_factory()
    try:
        upload_execute.reconcile_held_seeds(session, data_dir)
    except Exception:
        logger.exception("Esito dei recheck degli upload non letto")
    finally:
        session.close()


UPDATE_JOB_ID = "update_check"
UPDATE_INTERVAL_SECONDS = 3600


def _check_updates(session_factory: sessionmaker) -> None:
    """Ogni ora, ma chiama GitHub solo se l'utente ha acceso il controllo
    automatico e sono passate 12 ore dall'ultimo (nazgarr/core/updates.py):
    accenderlo o spegnerlo non deve riprogrammare niente."""
    from nazgarr.core import updates

    session = session_factory()
    try:
        updates.check_if_due(session)
    except Exception:
        logger.exception("Controllo automatico degli aggiornamenti fallito")
    finally:
        session.close()


WATCH_JOB_ID = "upload_watch"


def _scan_watch_folders(session_factory: sessionmaker, worker) -> None:
    from nazgarr.upload import watch as upload_watch

    session = session_factory()
    try:
        upload_watch.scan(session, kick=worker.kick)
    except Exception:
        logger.exception("Giro della cartella osservata fallito")
    finally:
        session.close()


SCHEDULED_UPLOADS_JOB_ID = "upload_scheduled"
SCHEDULED_UPLOADS_INTERVAL_SECONDS = 30


def _start_due_uploads(session_factory: sessionmaker, worker) -> None:
    """Gli upload programmati la cui ora è arrivata: si sveglia la coda, che
    li prende nel suo ordine (nazgarr/upload/worker.py)."""
    from nazgarr.core.models import UploadJob
    from nazgarr.upload import jobs as upload_jobs

    session = session_factory()
    try:
        due = [
            job for job in session.query(UploadJob).filter(
                UploadJob.status == "queued", UploadJob.scheduled_at.isnot(None))
            if upload_jobs.is_due(job)
        ]
        if due:
            worker.kick(due[0].id, "queued")
    except Exception:
        logger.exception("Controllo degli upload programmati fallito")
    finally:
        session.close()


def add_watch_job(scheduler: BackgroundScheduler, session_factory: sessionmaker, worker) -> None:
    """La cartella osservata per le release (nazgarr/upload/watch.py): serve il
    worker degli upload per svegliarlo sui job creati, quindi si aggiunge
    dopo averlo creato."""
    from nazgarr.upload import watch as upload_watch

    scheduler.add_job(
        _scan_watch_folders, IntervalTrigger(seconds=upload_watch.INTERVAL_SECONDS),
        args=[session_factory, worker], id=WATCH_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
    )
    # Gli upload programmati: anche questo ha bisogno del worker.
    scheduler.add_job(
        _start_due_uploads, IntervalTrigger(seconds=SCHEDULED_UPLOADS_INTERVAL_SECONDS),
        args=[session_factory, worker], id=SCHEDULED_UPLOADS_JOB_ID, replace_existing=True, max_instances=1,
        coalesce=True,
    )


def build_scheduler(session_factory: sessionmaker, data_dir: str) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(job_defaults=_JOB_DEFAULTS)
    with session_factory() as session:
        cron_expr = settings_repo.get_setting(session, SETTING_KEY)
    if cron_expr:
        try:
            _add_job(scheduler, cron_expr, session_factory, data_dir)
        except ValueError:
            # Un cron salvato che non si legge (scritto prima che l'API
            # generica lo rifiutasse, o a mano nel DB) non deve fermare
            # l'avvio: prima l'eccezione usciva dalla lifespan, e supervisord
            # riavviava in loop un processo che non partiva mai, senza
            # un'interfaccia per correggerlo (audit 2026-10-18). Si parte
            # senza scansioni pianificate; da Impostazioni se ne salva uno
            # nuovo (PUT /api/schedule).
            logger.exception("Il cron delle scansioni salvato (%r) non è valido: nessuna scansione pianificata",
                             cron_expr)
        else:
            _plan_catch_up(scheduler, session_factory, data_dir, cron_expr)
    scheduler.add_job(
        _reconcile_between_runs, IntervalTrigger(seconds=RECONCILE_INTERVAL_SECONDS),
        args=[session_factory], id=RECONCILE_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _deliver_events, IntervalTrigger(seconds=EVENTS_INTERVAL_SECONDS),
        args=[session_factory], id=EVENTS_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _apply_arr_webhook_events, IntervalTrigger(seconds=ARR_HOOKS_INTERVAL_SECONDS),
        args=[session_factory, data_dir], id=ARR_HOOKS_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _reconcile_held_seeds, IntervalTrigger(seconds=HELD_SEEDS_INTERVAL_SECONDS),
        args=[session_factory, data_dir], id=HELD_SEEDS_JOB_ID, replace_existing=True, max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _check_updates, IntervalTrigger(seconds=UPDATE_INTERVAL_SECONDS),
        args=[session_factory], id=UPDATE_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
    )
    return scheduler


def reschedule(
    scheduler: BackgroundScheduler, cron_expr: str | None, session_factory: sessionmaker, data_dir: str
) -> None:
    """Riconfigura (o rimuove, se cron_expr è vuoto/None) il job schedulato
    a runtime, chiamata da nazgarr/api/schedule.py dopo un aggiornamento.

    Le ore si contano da adesso: con un cron nuovo, un'ora di prima che non
    c'era (o di un cron tolto mesi fa) non è un'ora persa. Un recupero
    ancora in attesa si ricontrolla quando scatta (_catch_up), e trova il
    riferimento spostato."""
    if scheduler.get_job(JOB_ID) is not None:
        scheduler.remove_job(JOB_ID)
    if not cron_expr and scheduler.get_job(CATCH_UP_JOB_ID) is not None:
        scheduler.remove_job(CATCH_UP_JOB_ID)
    if cron_expr:
        _add_job(scheduler, cron_expr, session_factory, data_dir)
        with session_factory() as session:
            _record_slot(session)
