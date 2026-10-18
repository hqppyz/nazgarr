"""L'app dei test non fa lavoro in background se il test non lo chiede
(tests/conftest.py::_quiet_background, audit 2026-10-18)."""

import pytest
from apscheduler.schedulers.base import STATE_PAUSED, STATE_RUNNING


def test_the_test_app_has_its_jobs_but_never_runs_them(client):
    scheduler = client.app.state.scheduler
    assert scheduler.state == STATE_PAUSED
    assert {job.id for job in scheduler.get_jobs()} >= {"upload_watch"}
    assert type(client.app.state.upload_worker).__name__ == "QuietUploadWorker"

    # Lo scheduler resta modificabile come quello vero (la pianificazione delle run).
    assert client.put("/api/schedule", json={"cron": "* * * * *"}).status_code == 200
    assert scheduler.get_job("scheduled_run") is not None
    assert scheduler.state == STATE_PAUSED


def test_a_new_install_starts_quiet_too(anon_client):
    assert anon_client.app.state.scheduler.state == STATE_PAUSED


@pytest.mark.background
def test_a_test_can_ask_for_the_real_background_work(client):
    from nazgarr.upload.worker import UploadWorker

    assert client.app.state.scheduler.state == STATE_RUNNING
    assert type(client.app.state.upload_worker) is UploadWorker
