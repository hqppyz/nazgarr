from apscheduler.schedulers.background import BackgroundScheduler

from nazgarr import scheduler
from nazgarr.core.models import AppSetting


def test_build_scheduler_no_job_when_no_cron_configured(db_session):
    session_factory = _factory_returning(db_session)

    sched = scheduler.build_scheduler(session_factory, "/tmp/data")

    assert sched.get_job(scheduler.JOB_ID) is None


def test_build_scheduler_adds_job_when_cron_configured(db_session):
    db_session.add(AppSetting(key=scheduler.SETTING_KEY, value="0 3 * * *"))
    db_session.commit()
    session_factory = _factory_returning(db_session)

    sched = scheduler.build_scheduler(session_factory, "/tmp/data")

    job = sched.get_job(scheduler.JOB_ID)
    assert job is not None


def test_reschedule_replaces_existing_job(db_session):
    sched = BackgroundScheduler()
    session_factory = _factory_returning(db_session)

    scheduler.reschedule(sched, "0 3 * * *", session_factory, "/tmp/data")
    assert sched.get_job(scheduler.JOB_ID) is not None

    scheduler.reschedule(sched, "0 4 * * *", session_factory, "/tmp/data")
    job = sched.get_job(scheduler.JOB_ID)
    assert job is not None
    assert "4" in str(job.trigger)


def test_reschedule_with_none_removes_job(db_session):
    sched = BackgroundScheduler()
    session_factory = _factory_returning(db_session)
    scheduler.reschedule(sched, "0 3 * * *", session_factory, "/tmp/data")

    scheduler.reschedule(sched, None, session_factory, "/tmp/data")

    assert sched.get_job(scheduler.JOB_ID) is None


def _factory_returning(session):
    class _CtxSession:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    def factory():
        return _CtxSession() if session is not None else session

    return factory


def test_a_scheduled_run_is_skipped_while_another_is_in_progress(db_session, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from nazgarr.core.models import RunLog
    from nazgarr.reseed import pipeline

    pipeline.start_run(db_session, run_type="bulk_import")  # una run a mano, ancora in corso
    started = []
    monkeypatch.setattr(pipeline, "run_bulk_import", lambda *a, **k: started.append(a))
    scheduler._run_scheduled(sessionmaker(bind=db_session.get_bind()), "/tmp")
    assert started == [] and db_session.query(RunLog).count() == 1


def test_the_scheduled_scan_never_overlaps_itself(db_session):
    db_session.add(AppSetting(key=scheduler.SETTING_KEY, value="0 3 * * *"))
    db_session.commit()
    job = scheduler.build_scheduler(_factory_returning(db_session), "/tmp/data").get_job(scheduler.JOB_ID)
    assert job.max_instances == 1 and job.coalesce is True


def test_an_invalid_stored_cron_does_not_stop_the_start(db_session, caplog):
    """Prima build_scheduler sollevava ValueError dentro la lifespan: l'app
    non partiva più, e l'interfaccia per correggerlo nemmeno (audit 2026-10-18)."""
    for bad in ("every night please", "61 * * * *", "0 4 * * * *"):
        db_session.merge(AppSetting(key=scheduler.SETTING_KEY, value=bad))
        db_session.commit()
        caplog.clear()

        sched = scheduler.build_scheduler(_factory_returning(db_session), "/tmp/data")

        assert sched.get_job(scheduler.JOB_ID) is None
        assert sched.get_job(scheduler.RECONCILE_JOB_ID) is not None  # il resto c'è
        assert any("non è valido" in r.getMessage() for r in caplog.records)


def test_a_late_wakeup_still_runs_the_scheduled_scan(db_session):
    """Col default di APScheduler (1 s) un'ora passata con l'host in
    sospensione si scartava fino al giorno dopo."""
    db_session.add(AppSetting(key=scheduler.SETTING_KEY, value="0 3 * * *"))
    db_session.commit()
    sched = scheduler.build_scheduler(_factory_returning(db_session), "/tmp/data")
    assert sched.get_job(scheduler.JOB_ID).misfire_grace_time is None
    sched.start(paused=True)  # i default si applicano ai job quando parte
    try:
        assert sched.get_job(scheduler.EVENTS_JOB_ID).misfire_grace_time is None
    finally:
        sched.shutdown(wait=False)

    other = BackgroundScheduler()
    scheduler.reschedule(other, "0 4 * * *", _factory_returning(db_session), "/tmp/data")
    assert other.get_job(scheduler.JOB_ID).misfire_grace_time is None


# --- il recupero di un'ora persa con Nazgarr fermo (decisione dell'utente, 2026-10-18)


def _with_cron(db_session, cron="0 3 * * *", last=None):
    from nazgarr.core import settings_repo

    settings_repo.set_setting(db_session, scheduler.SETTING_KEY, cron)
    if last is not None:
        settings_repo.set_setting(db_session, scheduler.LAST_SLOT_KEY, last.isoformat())


def _slot_ago(cron: str, days: int):
    """Un'ora del cron di `days` giorni fa, nel fuso dello scheduler."""
    from datetime import UTC, datetime, timedelta

    from apscheduler.triggers.cron import CronTrigger

    trigger = CronTrigger.from_crontab(cron)
    return trigger.get_next_fire_time(None, datetime.now(UTC) - timedelta(days=days))


def test_a_slot_missed_while_stopped_runs_once_at_startup(db_session):
    from datetime import timedelta

    # L'ultima servita due giorni fa: ne ha perse due (ieri e l'altro ieri), si recupera una volta sola.
    last = _slot_ago("0 3 * * *", 3) + timedelta(seconds=1)
    _with_cron(db_session, last=last)

    sched = scheduler.build_scheduler(_factory_returning(db_session), "/tmp/data")

    job = sched.get_job(scheduler.CATCH_UP_JOB_ID)
    assert job is not None and job.misfire_grace_time is None and job.max_instances == 1
    assert [j.id for j in sched.get_jobs()].count(scheduler.CATCH_UP_JOB_ID) == 1
    assert sched.get_job(scheduler.JOB_ID) is not None  # il cron resta com'era


def test_no_catch_up_when_no_slot_was_missed(db_session):
    from datetime import UTC, datetime

    _with_cron(db_session, last=datetime.now(UTC))

    sched = scheduler.build_scheduler(_factory_returning(db_session), "/tmp/data")

    assert sched.get_job(scheduler.CATCH_UP_JOB_ID) is None


def test_the_first_start_sets_a_reference_and_does_not_catch_up(db_session):
    """Nessun riferimento (la prima volta, nessuna run pianificata): da adesso."""
    from nazgarr.core import settings_repo

    _with_cron(db_session)

    sched = scheduler.build_scheduler(_factory_returning(db_session), "/tmp/data")

    assert sched.get_job(scheduler.CATCH_UP_JOB_ID) is None
    assert settings_repo.get_setting(db_session, scheduler.LAST_SLOT_KEY)


def test_without_the_key_the_last_scheduled_run_is_the_reference(db_session):
    """Un DB di prima della chiave: conta l'inizio dell'ultima run pianificata."""
    from datetime import timedelta

    from nazgarr.core.models import RunLog

    _with_cron(db_session)
    started = _slot_ago("0 3 * * *", 3)
    db_session.add(RunLog(run_type="scheduled", started_at=(started + timedelta(seconds=5)).replace(tzinfo=None),
                          finished_at=(started + timedelta(minutes=5)).replace(tzinfo=None)))
    db_session.commit()

    sched = scheduler.build_scheduler(_factory_returning(db_session), "/tmp/data")

    assert sched.get_job(scheduler.CATCH_UP_JOB_ID) is not None


def test_a_slot_that_fired_counts_even_when_it_found_a_run_in_progress(db_session, monkeypatch):
    """Saltata per una run in corso, l'ora è servita: nessun recupero dopo."""
    from datetime import timedelta

    from sqlalchemy.orm import sessionmaker

    from nazgarr.reseed import pipeline

    _with_cron(db_session, last=_slot_ago("0 3 * * *", 3) + timedelta(seconds=1))
    pipeline.start_run(db_session, run_type="bulk_import")
    monkeypatch.setattr(pipeline, "run_bulk_import", lambda *a, **k: None)

    scheduler._run_scheduled(sessionmaker(bind=db_session.get_bind()), "/tmp")

    db_session.expire_all()
    assert scheduler.missed_slot(db_session, "0 3 * * *") is None


def test_the_catch_up_checks_again_before_starting(db_session, monkeypatch):
    """Fra l'avvio e il recupero l'ora può essere scattata da sola, o il
    cron cambiato: allora niente, e mai due scansioni."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.orm import sessionmaker

    started = []
    monkeypatch.setattr(scheduler, "_run_scheduled", lambda *a: started.append(a))
    factory = sessionmaker(bind=db_session.get_bind())

    _with_cron(db_session, last=_slot_ago("0 3 * * *", 3) + timedelta(seconds=1))
    scheduler._catch_up(factory, "/tmp")
    assert len(started) == 1

    _with_cron(db_session, last=datetime.now(UTC))  # scattata nel frattempo
    scheduler._catch_up(factory, "/tmp")
    assert len(started) == 1


def test_a_new_cron_counts_its_slots_from_now(db_session):
    """Cambiare il cron (o impostarne uno dopo mesi) non fa di un'ora che non
    c'era un'ora persa al riavvio dopo."""
    from datetime import timedelta

    _with_cron(db_session, last=_slot_ago("0 3 * * *", 3) + timedelta(seconds=1))
    sched = BackgroundScheduler()

    scheduler.reschedule(sched, "0 4 * * *", _factory_returning(db_session), "/tmp/data")

    assert scheduler.missed_slot(db_session, "0 4 * * *") is None
    rebuilt = scheduler.build_scheduler(_factory_returning(db_session), "/tmp/data")
    assert rebuilt.get_job(scheduler.CATCH_UP_JOB_ID) is None


def test_removing_the_cron_drops_a_pending_catch_up(db_session):
    from datetime import timedelta

    _with_cron(db_session, last=_slot_ago("0 3 * * *", 3) + timedelta(seconds=1))
    sched = scheduler.build_scheduler(_factory_returning(db_session), "/tmp/data")
    assert sched.get_job(scheduler.CATCH_UP_JOB_ID) is not None

    scheduler.reschedule(sched, None, _factory_returning(db_session), "/tmp/data")

    assert sched.get_job(scheduler.CATCH_UP_JOB_ID) is None and sched.get_job(scheduler.JOB_ID) is None


def test_the_catch_up_key_is_not_writable_from_the_generic_api(client):
    response = client.put("/api/settings/schedule_last_slot", json={"value": "2020-01-01T00:00:00+00:00"})
    assert response.status_code == 403
