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


def test_client_labels_of_a_reseed_are_chosen_on_its_review(client):
    from nazgarr.core.models import TorrentClient

    session = _session(client)
    try:
        qb = TorrentClient(label="qb", adapter_type="qbittorrent", base_url="http://qb.test", category_tv="tv",
                           tags_reseed="reseed")
        tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
        item = MediaItem(content_type="tv", tmdb_id=2)
        session.add_all([qb, tracker, item])
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
        review_id, client_id = match_review.id, qb.id
    finally:
        session.close()

    [listed] = client.get("/api/reviews").json()
    # I default del client, come li vedrebbe il reseed senza scelte.
    assert (listed["torrent_client_id"], listed["default_client_category"], listed["default_client_tags"]) == (
        client_id, "tv", "reseed")
    assert (listed["client_category"], listed["client_tags"]) == (None, None)

    chosen = client.put(f"/api/reviews/{review_id}/client-labels",
                        json={"client_category": "anime", "client_tags": "a, b"}).json()
    assert (chosen["client_category"], chosen["client_tags"]) == ("anime", "a,b")
    back = client.put(f"/api/reviews/{review_id}/client-labels", json={}).json()
    assert (back["client_category"], back["client_tags"]) == (None, None)

    client.post(f"/api/reviews/{review_id}/reject")
    assert client.put(f"/api/reviews/{review_id}/client-labels", json={}).status_code == 409
