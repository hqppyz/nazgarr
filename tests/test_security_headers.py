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
