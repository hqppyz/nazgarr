"""Il tetto al corpo delle richieste (nazgarr/web/body_limit.py): prima del
login, prima di qualunque lettura completa."""

import json

import anyio

from nazgarr.web.body_limit import MAX_BODY_BYTES

CHUNK = 64 * 1024


def _send_request(app, path, *, chunks, headers=(), method="POST"):
    """Una richiesta ASGI a mano: `chunks` sono i pezzi del corpo (anche
    infiniti). Restituisce lo status, il corpo della risposta e quanti pezzi
    l'app ha chiesto."""
    reads = 0
    sent = []
    pieces = iter(chunks)

    async def receive():
        nonlocal reads
        reads += 1
        piece = next(pieces, None)
        if piece is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.request", "body": piece, "more_body": True}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"), *headers],
        "client": ("10.0.0.9", 40000), "server": ("testserver", 80),
    }
    anyio.run(app, scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], body, reads


def _endless():
    while True:
        yield b"0" * CHUNK


def test_a_declared_body_over_the_limit_is_refused_without_reading_it(anon_client):
    length = str(MAX_BODY_BYTES + 1).encode()
    status, body, reads = _send_request(anon_client.app, "/api/auth/login", chunks=_endless(),
                                        headers=[(b"content-length", length)])
    assert status == 413
    assert json.loads(body)["detail"]["code"] == "request_too_large"
    assert reads == 0


def test_an_endless_chunked_body_stops_at_the_limit(anon_client):
    # Prima: tutto il corpo in memoria, poi 422. Ora si ferma appena passa il tetto.
    for path in ("/api/auth/login", "/api/auth/setup", "/api/disks"):
        status, body, reads = _send_request(anon_client.app, path, chunks=_endless())
        assert status == 413, path
        assert json.loads(body)["detail"]["code"] == "request_too_large"
        assert reads <= MAX_BODY_BYTES // CHUNK + 1


def test_a_normal_body_still_goes_through(anon_client):
    payload = json.dumps({"username": "admin", "password": "x" * (MAX_BODY_BYTES // 2)}).encode()
    status, _, _ = _send_request(anon_client.app, "/api/auth/login", chunks=[payload],
                                 headers=[(b"content-length", str(len(payload)).encode())])
    assert status == 401  # letto e controllato: nessun account ancora
