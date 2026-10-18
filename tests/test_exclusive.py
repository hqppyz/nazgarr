"""Run e lavoro a lato mai insieme (nazgarr/reseed/exclusive.py, audit
2026-10-18): prima il lavoro a lato controllava solo che nessuna run fosse
in corso, e una run poteva partire a metà."""

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from nazgarr.core import db
from nazgarr.core.models import ArrWebhookEvent, RadarrInstance, RunLog
from nazgarr.integrations import arr_webhooks
from nazgarr.reseed import exclusive, pipeline


def _hold_side_work(session_factory, started: threading.Event, release: threading.Event) -> threading.Thread:
    def work():
        session = session_factory()
        try:
            with exclusive.side_work(session):
                started.set()
                release.wait(5)
        finally:
            session.close()

    thread = threading.Thread(target=work)
    thread.start()
    assert started.wait(5)
    return thread


@pytest.fixture
def factory(db_session):
    return db.make_session_factory(db_session.get_bind())


def test_a_scheduled_run_waits_for_the_side_work_instead_of_starting_halfway(db_session, factory):
    started, release = threading.Event(), threading.Event()
    holder = _hold_side_work(factory, started, release)
    order = []

    def scheduled():
        session = factory()
        try:
            pipeline.try_start_run(session, run_type="scheduled")
            order.append("run started")
        finally:
            session.close()

    runner = threading.Thread(target=scheduled)
    runner.start()
    time.sleep(0.2)
    order.append("side work done")
    release.set()
    holder.join(5)
    runner.join(5)

    assert order == ["side work done", "run started"]


def test_scan_now_waits_a_little_then_gives_up(db_session, factory):
    started, release = threading.Event(), threading.Event()
    holder = _hold_side_work(factory, started, release)
    try:
        with pytest.raises(exclusive.Busy) as busy:  # nessuna run: il lavoro a lato non è finito
            exclusive.start_run(db_session, "bulk_import", wait_seconds=0.1)
        assert busy.value.code == "side_work_in_progress"
    finally:
        release.set()
        holder.join(5)

    assert exclusive.start_run(db_session, "bulk_import", wait_seconds=0.1).finished_at is None


def test_side_work_never_runs_with_a_run_or_another_side_work(db_session, factory):
    started, release = threading.Event(), threading.Event()
    holder = _hold_side_work(factory, started, release)
    try:
        with pytest.raises(exclusive.Busy) as busy:  # un altro lavoro a lato
            with exclusive.side_work(db_session):
                pytest.fail("must not run")
        assert busy.value.code == "side_work_in_progress"
    finally:
        release.set()
        holder.join(5)

    pipeline.start_run(db_session, "manual")
    with pytest.raises(exclusive.Busy) as busy:  # una run in corso
        with exclusive.side_work(db_session):
            pytest.fail("must not run")
    assert busy.value.code == "run_in_progress"


def test_webhook_events_wait_while_other_side_work_runs(db_session, factory):
    radarr = RadarrInstance(label="r", base_url="http://radarr:7878", api_key="k", webhook_token="t")
    db_session.add(radarr)
    db_session.commit()
    arr_webhooks.receive(db_session, "radarr", radarr, {"eventType": "Test"})
    later = datetime.now(UTC) + timedelta(minutes=1)
    started, release = threading.Event(), threading.Event()
    holder = _hold_side_work(factory, started, release)
    try:
        assert arr_webhooks.process_pending(db_session, now=later) == 0
    finally:
        release.set()
        holder.join(5)
    assert db_session.query(ArrWebhookEvent).one().status == "pending"

    assert arr_webhooks.process_pending(db_session, now=later) == 1
    assert db_session.query(RunLog).count() == 0


def test_search_now_is_refused_while_side_work_runs(client, monkeypatch):
    """Il 409 dice che è il lavoro a lato, non una scansione (revisione
    dell'audit 2026-10-18): prima diceva "C'è una scansione in corso" anche
    senza nessuna run."""
    monkeypatch.setattr(exclusive, "START_WAIT_SECONDS", 0.1)
    started, release = threading.Event(), threading.Event()
    holder = _hold_side_work(client.app.state.session_factory, started, release)
    try:
        response = client.post("/api/library/items/movie/603/search")
        refresh = client.post("/api/torrents/not-imported/refresh")
        scan = client.post("/api/runs")
    finally:
        release.set()
        holder.join(5)

    for refused in (response, refresh, scan):
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "side_work_in_progress"
    # Finito il lavoro a lato, la ricerca risponde di nuovo (qui: nessun file di quel contenuto).
    assert client.post("/api/library/items/movie/603/search").status_code == 404


def test_search_now_during_a_run_says_a_scan_is_in_progress(client):
    session = client.app.state.session_factory()
    try:
        pipeline.start_run(session, "manual")
    finally:
        session.close()

    response = client.post("/api/library/items/movie/603/search")

    assert response.status_code == 409 and response.json()["detail"]["code"] == "run_in_progress"


def test_reconcile_now_and_deleting_an_execution_wait_for_the_side_work(client):
    """Audit 2026-10-18: controllavano solo che nessuna run fosse in corso,
    poi lavoravano senza tenere niente, e una run poteva partire a metà."""
    from nazgarr.core.models import Candidate, MediaItem, SeedJob, Tracker

    db_session = client.app.state.session_factory()
    item = MediaItem(content_type="movie", tmdb_id=1)
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    db_session.add_all([item, tracker])
    db_session.commit()
    candidate = Candidate(media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x",
                          size_bytes=1, source="catalog_search", direction="media_to_torrent", confidence=1.0)
    db_session.add(candidate)
    db_session.commit()
    job = SeedJob(candidate_id=candidate.id, final_status="failed")
    db_session.add(job)
    db_session.commit()

    started, release = threading.Event(), threading.Event()
    holder = _hold_side_work(client.app.state.session_factory, started, release)
    try:
        reconcile = client.post("/api/reviews/seed-jobs/reconcile")
        delete = client.delete(f"/api/reviews/seed-jobs/{job.id}")
    finally:
        release.set()
        holder.join(5)
    for refused in (reconcile, delete):
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "side_work_in_progress"

    session = client.app.state.session_factory()
    try:
        pipeline.start_run(session, "manual")
    finally:
        session.close()
    during_run = client.delete(f"/api/reviews/seed-jobs/{job.id}")
    assert during_run.status_code == 409 and during_run.json()["detail"]["code"] == "run_in_progress"
    assert client.post("/api/reviews/seed-jobs/reconcile").json()["detail"]["code"] == "run_in_progress"
    db_session.query(RunLog).update({RunLog.finished_at: datetime.now(UTC)})
    db_session.commit()

    assert client.post("/api/reviews/seed-jobs/reconcile").json() == {"reconciled": 0, "errors": 0}
    assert client.delete(f"/api/reviews/seed-jobs/{job.id}").status_code == 204
    db_session.close()
