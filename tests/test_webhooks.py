"""Eventi (nazgarr/core/events.py) e webhook (nazgarr/integrations/webhooks.py)."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx

from nazgarr.core import events
from nazgarr.core.models import Candidate, Event, EventDelivery, MatchReview, MediaItem, RunLog, SeedJob, Webhook
from nazgarr.integrations import webhooks
from tests.upload_helpers import make_tracker


def _webhook(session, names=("*",), url="https://hooks.example/nazgarr", secret="s3cret"):
    webhook = Webhook(name="hook", url=url, secret=secret, events_json=json.dumps(list(names)))
    session.add(webhook)
    session.commit()
    return webhook


def _candidate(session):
    tracker = make_tracker(session, "ITT", with_profile=False)
    item = MediaItem(content_type="movie", tmdb_id=603)
    session.add(item)
    session.commit()
    candidate = Candidate(media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="7", name="The.Matrix.1999",
                          size_bytes=1, source="catalog_search", direction="media_to_torrent", confidence=0.91)
    session.add(candidate)
    session.commit()
    return candidate


def _events(session):
    return [(e.name, json.loads(e.payload_json)) for e in session.query(Event).order_by(Event.id)]


def test_nothing_is_stored_without_a_subscriber(db_session):
    candidate = _candidate(db_session)
    db_session.add(MatchReview(candidate_id=candidate.id, status="pending"))
    db_session.commit()
    assert db_session.query(Event).count() == 0


def test_state_changes_in_the_db_become_events(db_session):
    _webhook(db_session)
    candidate = _candidate(db_session)

    review = MatchReview(candidate_id=candidate.id, status="pending")
    db_session.add(review)
    db_session.commit()
    review.status, review.decided_by = "approved", "user"
    db_session.commit()
    job = SeedJob(candidate_id=candidate.id, final_status="in_progress")
    db_session.add(job)
    db_session.commit()
    job.final_status, job.info_hash = "seeding", "abc"
    db_session.commit()
    run = RunLog(run_type="manual", started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    run.finished_at, run.errors = datetime.now(UTC), 0
    db_session.commit()

    names = [name for name, _ in _events(db_session)]
    assert names == ["review.created", "review.decided", "seed_job.finished", "run.finished"]
    created, decided, seeded, finished = (data for _, data in _events(db_session))
    assert (created["status"], created["tracker"], created["torrent"], created["confidence"]) == (
        "pending", "ITT", "The.Matrix.1999", 0.91)
    assert (decided["status"], decided["decided_by"]) == ("approved", "user")
    assert (seeded["status"], seeded["info_hash"]) == ("seeding", "abc")
    assert finished["run_id"] == run.id and finished["stopped"] is False
    assert db_session.query(EventDelivery).filter_by(status="pending").count() == 4


def test_a_webhook_only_gets_the_events_it_chose(db_session):
    _webhook(db_session, names=["run.finished"])
    candidate = _candidate(db_session)
    db_session.add(MatchReview(candidate_id=candidate.id, status="pending"))
    db_session.commit()
    assert db_session.query(Event).count() == 0


def _transport(responses, seen):
    def handler(request):
        seen.append(request)
        return responses.pop(0) if responses else httpx.Response(200)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_delivery_is_signed_and_retried_with_backoff(db_session):
    _webhook(db_session, names=["test"])
    events.store(db_session, "test", {"hello": "world"})
    db_session.commit()
    seen = []
    now = datetime.now(UTC)
    client = _transport([httpx.Response(500, text="down"), httpx.Response(204)], seen)

    assert webhooks.deliver_due(db_session, client, now) == 1
    delivery = db_session.query(EventDelivery).one()
    # Un evento "test" non si ritenta; per il ritentativo uso un evento vero.
    assert delivery.status == "failed" and delivery.last_status_code == 500

    request = seen[0]
    body = request.content
    expected = hmac.new(b"s3cret", request.headers["X-Nazgarr-Timestamp"].encode() + b"." + body,
                        hashlib.sha256).hexdigest()
    assert request.headers["X-Nazgarr-Signature"] == f"sha256={expected}"
    assert request.headers["X-Nazgarr-Event"] == "test"
    assert json.loads(body)["data"] == {"hello": "world"}


def test_backoff_then_delivered_then_failed_after_the_last_attempt(db_session):
    _webhook(db_session, names=["run.finished"])
    events.store(db_session, "run.finished", {"run_id": 1})
    db_session.commit()
    delivery = db_session.query(EventDelivery).one()
    now = datetime.now(UTC)

    webhooks.deliver_due(db_session, _transport([httpx.Response(502)], []), now)
    assert (delivery.status, delivery.attempts) == ("pending", 1)
    assert delivery.next_attempt_at.replace(tzinfo=UTC) - now == webhooks.BACKOFF[0]
    # Prima del suo momento non si ritenta.
    assert webhooks.deliver_due(db_session, _transport([], []), now + timedelta(seconds=30)) == 0
    webhooks.deliver_due(db_session, _transport([httpx.Response(200)], []), now + timedelta(minutes=2))
    assert delivery.status == "delivered" and delivery.attempts == 2

    events.store(db_session, "run.finished", {"run_id": 2})
    db_session.commit()
    other = db_session.query(EventDelivery).filter_by(status="pending").one()
    later = now
    for _ in range(webhooks.MAX_ATTEMPTS):
        later += timedelta(hours=7)
        webhooks.deliver_due(db_session, _transport([httpx.Response(500)], []), later)
    assert (other.status, other.attempts) == ("failed", webhooks.MAX_ATTEMPTS)


def test_old_events_are_pruned(db_session):
    _webhook(db_session)
    events.store(db_session, "run.finished", {"run_id": 1})
    db_session.commit()
    webhooks.deliver_due(db_session, _transport([], []), datetime.now(UTC) + timedelta(days=31))
    assert db_session.query(Event).count() == 0 and db_session.query(EventDelivery).count() == 0


def test_the_webhooks_api(client, monkeypatch):
    assert "seed_job.finished" in [e["name"] for e in client.get("/api/webhooks/events").json()]
    assert client.post("/api/webhooks", json={"name": "x", "url": "ftp://x", "events": ["*"]}).status_code == 400
    assert client.post("/api/webhooks", json={"name": "x", "url": "https://x", "events": ["nope"]}).status_code == 400

    created = client.post("/api/webhooks", json={"name": "discord", "url": "https://hooks.example/a",
                                                  "events": ["upload.finished"]})
    assert created.status_code == 201
    secret = created.json()["secret"]
    listed = client.get("/api/webhooks")
    assert secret not in listed.text and listed.json()[0]["events"] == ["upload.finished"]

    seen = []
    real_client = httpx.Client
    fake = real_client(transport=httpx.MockTransport(lambda request: (seen.append(request), httpx.Response(200))[1]))
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    hook_id = created.json()["id"]
    tested = client.post(f"/api/webhooks/{hook_id}/test").json()
    assert (tested["event"], tested["status"]) == ("test", "delivered")
    assert json.loads(seen[0].content)["data"]["webhook"] == "discord"
    assert client.get(f"/api/webhooks/{hook_id}/deliveries").json()[0]["status"] == "delivered"

    rotated = client.post(f"/api/webhooks/{hook_id}/rotate-secret").json()["secret"]
    assert rotated != secret
    assert client.delete(f"/api/webhooks/{hook_id}").status_code == 204


def test_an_upload_that_finishes_emits_upload_finished(db_session):
    from nazgarr.core.models import UploadJob, UploadTarget
    from nazgarr.upload import jobs as upload_jobs

    _webhook(db_session, names=["upload.finished"])
    tracker = make_tracker(db_session, "ITT", with_profile=False)
    job = UploadJob(relative_path="media/Movie.mkv", source_path="/mnt/d/media/Movie.mkv", status="running",
                    title="Movie", year=2024)
    job.targets = [UploadTarget(tracker_id=tracker.id, status="done", action="upload", torrent_id_remote="42")]
    db_session.add(job)
    db_session.commit()

    assert upload_jobs.transition(db_session, job, "running", "done")

    [(name, data)] = _events(db_session)
    assert (name, data["status"], data["title"]) == ("upload.finished", "done", "Movie")
    assert data["targets"] == [{"tracker": "ITT", "action": "upload", "status": "done", "torrent_id_remote": "42",
                                "error": None}]


def test_a_webhook_to_the_cloud_metadata_is_refused(client):
    body = {"name": "x", "url": "http://169.254.169.254/latest", "events": ["*"]}
    assert client.post("/api/webhooks", json=body).status_code == 400


def test_a_webhook_never_stores_the_response_body(db_session):
    _webhook(db_session, names=["run.finished"], url="http://192.168.1.20/hook")
    events.store(db_session, "run.finished", {"run_id": 1})
    db_session.commit()
    secret_page = httpx.Response(500, text="internal admin page: password=hunter2")
    webhooks.deliver_due(db_session, _transport([secret_page], []))
    delivery = db_session.query(EventDelivery).one()
    assert delivery.last_status_code == 500 and "hunter2" not in delivery.last_error
