"""Setup diretto via session_factory dell'app (esposta dal client fixture)
per creare candidate/match_review senza dover passare da uno scan+match
completo, che richiederebbe un tracker/client reali."""

from nazgarr.core.models import Candidate, MatchReview, MediaItem, Tracker


def _session(client):
    return client.app.state.session_factory()


def test_list_reviews_empty(client):
    response = client.get("/api/reviews")
    assert response.status_code == 200
    assert response.json() == []


def test_approve_and_reject_review(client):
    session = _session(client)
    try:
        tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
        session.add(tracker)
        session.commit()
        item = MediaItem(content_type="movie", tmdb_id=1)
        session.add(item)
        session.commit()
        candidate = Candidate(
            media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x", size_bytes=1,
            source="catalog_search", direction="media_to_torrent", confidence=0.5,
        )
        session.add(candidate)
        session.commit()
        match_review = MatchReview(candidate_id=candidate.id, status="pending")
        session.add(match_review)
        session.commit()
        review_id = match_review.id
    finally:
        session.close()

    listed = client.get("/api/reviews").json()
    assert len(listed) == 1
    assert listed[0]["id"] == review_id
    assert listed[0]["direction"] == "media_to_torrent"

    reject = client.post(f"/api/reviews/{review_id}/reject")
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    assert client.get("/api/reviews").json() == []


def test_approve_nonexistent_review_404(client):
    response = client.post("/api/reviews/999/approve")
    assert response.status_code == 404
