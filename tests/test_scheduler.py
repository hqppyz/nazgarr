from apscheduler.schedulers.background import BackgroundScheduler

from nazgarr import scheduler
from nazgarr.models import AppSetting


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


def test_reschedule_replaces_existing_job():
    sched = BackgroundScheduler()
    session_factory = _factory_returning(None)

    scheduler.reschedule(sched, "0 3 * * *", session_factory, "/tmp/data")
    assert sched.get_job(scheduler.JOB_ID) is not None

    scheduler.reschedule(sched, "0 4 * * *", session_factory, "/tmp/data")
    job = sched.get_job(scheduler.JOB_ID)
    assert job is not None
    assert "4" in str(job.trigger)


def test_reschedule_with_none_removes_job():
    sched = BackgroundScheduler()
    session_factory = _factory_returning(None)
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

    from nazgarr import pipeline
    from nazgarr.models import RunLog

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
