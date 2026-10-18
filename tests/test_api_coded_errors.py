"""Gli errori dell'API sono {code, params} (nazgarr/core/errors.py), che
l'interfaccia traduce: mai un testo libero, a volte italiano o con dentro
il messaggio di un client (audit 2026-10-18)."""

import re
from pathlib import Path

from nazgarr.core.models import Candidate, MatchReview, MediaItem, Tracker

API = Path(__file__).resolve().parent.parent / "nazgarr" / "api"
# L'unica eccezione: il retry di un'esecuzione fallita risponde col testo
# inglese, già ripulito da safe_error, dell'errore che l'ha fermata (un
# client, un tracker): non ha un codice.
FREE_TEXT_ALLOWED = {("reviews.py", "retry_failed")}


def _function_at(lines: list[str], index: int) -> str | None:
    for line in reversed(lines[:index]):
        match = re.match(r"(?:async\s+)?def (\w+)", line)
        if match:
            return match.group(1)
    return None


def test_no_api_error_detail_is_a_literal_or_the_text_of_an_exception():
    offenders = []
    for path in sorted(API.glob("*.py")):
        lines = path.read_text().splitlines()
        for number, line in enumerate(lines, start=1):
            if re.search(r"""detail=(str\(|["'])""", line):
                offenders.append(f"{path.name}:{number}")
            elif "detail=safe_error(" in line and (path.name, _function_at(lines, number)) not in FREE_TEXT_ALLOWED:
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
    from nazgarr.core.models import SeedJob

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
