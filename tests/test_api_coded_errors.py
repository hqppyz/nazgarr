"""Gli errori dell'API sono {code, params} (nazgarr/core/errors.py), che
l'interfaccia traduce: mai un testo libero, a volte italiano o con dentro
il messaggio di un client (audit 2026-10-18)."""

import re
from pathlib import Path

from nazgarr.core.models import Candidate, MatchReview, MediaItem, SeedJob, Tracker

API = Path(__file__).resolve().parent.parent / "nazgarr" / "api"


def test_no_api_error_detail_is_a_literal_or_the_text_of_an_exception():
    # Nessuna eccezione: anche il retry di un'esecuzione fallita ha i suoi
    # codici (seed_job_retry_failed col testo inglese dell'errore, già
    # ripulito da safe_error; audit 2026-10-18, prima era il solo testo libero).
    offenders = []
    for path in sorted(API.glob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if re.search(r"""detail=(str\(|["']|safe_error\()""", line):
                offenders.append(f"{path.name}:{number}")
    assert offenders == []


def test_a_review_already_being_verified_answers_with_its_code(client):
    session = client.app.state.session_factory()
    try:
        tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
        item = MediaItem(content_type="movie", tmdb_id=1)
        session.add_all([tracker, item])
        session.commit()
        candidate = Candidate(media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x",
                              size_bytes=1, source="catalog_search", direction="media_to_torrent", confidence=0.5)
        session.add(candidate)
        session.commit()
        review = MatchReview(candidate_id=candidate.id, status="pending", verify_status="verifying")
        session.add(review)
        session.commit()
        review_id = review.id
    finally:
        session.close()

    response = client.post(f"/api/reviews/{review_id}/approve")

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "review_already_verifying", "params": {"id": review_id}}


def test_full_check_errors_answer_with_their_codes(client):
    missing = client.get("/api/full-checks/abc123")
    cancel = client.post("/api/full-checks/abc123/cancel")
    start = client.post("/api/full-checks", json={"candidate_id": 999})

    for response in (missing, cancel):
        assert response.status_code == 404
        assert response.json()["detail"] == {"code": "full_check_not_found", "params": {"id": "abc123"}}
    assert start.status_code == 404
    assert start.json()["detail"] == {"code": "full_check_candidate_not_found", "params": {"id": 999}}


def test_a_seed_job_that_cannot_be_deleted_answers_with_its_code(client):
    session = client.app.state.session_factory()
    try:
        tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
        item = MediaItem(content_type="movie", tmdb_id=1)
        session.add_all([tracker, item])
        session.commit()
        candidate = Candidate(media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x",
                              size_bytes=1, source="catalog_search", direction="media_to_torrent", confidence=0.5)
        session.add(candidate)
        session.commit()
        seed_job = SeedJob(candidate_id=candidate.id, final_status="seeding", info_hash="h1")
        session.add(seed_job)
        session.commit()
        seed_job_id = seed_job.id
    finally:
        session.close()

    response = client.delete(f"/api/reviews/seed-jobs/{seed_job_id}")

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "seed_job_not_deletable",
                                         "params": {"id": seed_job_id, "status": "seeding"}}


def _seed_job(session, **values):
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    item = MediaItem(content_type="movie", tmdb_id=1)
    session.add_all([tracker, item])
    session.commit()
    candidate = Candidate(media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x",
                          size_bytes=1, source="catalog_search", direction="media_to_torrent", confidence=0.5)
    session.add(candidate)
    session.commit()
    seed_job = SeedJob(candidate_id=candidate.id, **values)
    session.add(seed_job)
    session.commit()
    return seed_job.id


def test_a_retry_that_is_not_possible_answers_with_its_code(client):
    """Il 409 del retry era un testo libero (a volte italiano: "Nessun client
    torrent configurato"), che interfaccia e CLI non sapevano tradurre."""
    session = client.app.state.session_factory()
    try:
        seeding = _seed_job(session, final_status="seeding", info_hash="h1")
    finally:
        session.close()

    not_failed = client.post(f"/api/reviews/failed/{seeding}/retry")

    assert not_failed.status_code == 409
    assert not_failed.json()["detail"] == {"code": "seed_job_not_failed",
                                           "params": {"id": seeding, "status": "seeding"}}
    session = client.app.state.session_factory()
    try:
        session.get(SeedJob, seeding).final_status = "failed"
        session.commit()
    finally:
        session.close()
    no_client = client.post(f"/api/reviews/failed/{seeding}/retry")
    assert no_client.status_code == 409
    assert no_client.json()["detail"] == {"code": "seed_job_no_client", "params": {}}


def test_a_retry_that_fails_again_answers_with_a_code_and_the_english_error(client, monkeypatch):
    from nazgarr.adapters.torrent_client.base import TorrentAddTimeoutError
    from nazgarr.reseed import executor, review

    session = client.app.state.session_factory()
    try:
        seed_job_id = _seed_job(session, final_status="failed", info_hash="h1")
    finally:
        session.close()

    def fail_again(session, seed_job, session_factory=None):
        raise executor.ExecutionError(str(TorrentAddTimeoutError("Torrent h1 did not show up in qBittorrent")))

    monkeypatch.setattr(review, "retry_failed", fail_again)
    response = client.post(f"/api/reviews/failed/{seed_job_id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "seed_job_retry_failed",
        "params": {"id": seed_job_id, "error": "Torrent h1 did not show up in qBittorrent"},
    }
