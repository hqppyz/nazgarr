"""Il tetto al corpo delle richieste (nazgarr/web/body_limit.py): prima del
login, prima di qualunque lettura completa, e fuori da /api/auth/* nessun
corpo letto senza credenziali."""

import json

import anyio

from nazgarr.web.body_limit import LOGIN_BODY_BYTES, MAX_BODY_BYTES

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


def _length(payload: bytes):
    return (b"content-length", str(len(payload)).encode())


def _bearer(client):
    return (b"authorization", client.headers["Authorization"].encode())


def _empty_objects(size: int) -> bytes:
    """`[{},{},...]` di circa size byte: il JSON che costa di più da decodificare
    e da rimandare indietro in un 422 a parità di byte."""
    return ("[" + ",".join(["{}"] * ((size - 2) // 3)) + "]").encode()


def test_a_declared_body_over_the_limit_is_refused_without_reading_it(client):
    length = str(MAX_BODY_BYTES + 1).encode()
    for path in ("/api/auth/login", "/api/disks"):
        status, body, reads = _send_request(client.app, path, chunks=_endless(),
                                            headers=[(b"content-length", length), _bearer(client)])
        assert status == 413, path
        assert json.loads(body)["detail"]["code"] == "request_too_large"
        assert reads == 0


def test_a_crafted_body_just_under_the_global_limit_is_refused_before_the_login(anon_client):
    # Sotto i 2 MB, ma 0,7 s di loop e oltre 100 MB per il 422 che lo
    # rimandava indietro: una decina in parallelo fermava il processo
    # (audit 2026-10-18). Al login non serve più di qualche centinaio di byte.
    payload = _empty_objects(MAX_BODY_BYTES - 1)
    for path in ("/api/auth/login", "/api/auth/setup"):
        status, body, reads = _send_request(anon_client.app, path, chunks=[payload], headers=[_length(payload)])
        assert status == 413, path
        assert json.loads(body)["detail"] == {"code": "request_too_large", "params": {"limit": LOGIN_BODY_BYTES}}
        assert reads == 0


def test_without_credentials_no_body_is_read_outside_the_login(anon_client):
    # FastAPI decodifica il corpo prima delle dipendenze, quindi prima del 401
    # di require_auth: anche un corpo piccolo si ferma prima.
    for payload in (_empty_objects(MAX_BODY_BYTES - 1), b'{"path": "/mnt"}'):
        status, body, reads = _send_request(anon_client.app, "/api/disks", chunks=[payload],
                                            headers=[_length(payload)])
        assert status == 401 and json.loads(body)["detail"]["code"] == "auth_setup_required"
        assert reads == 0
    status, body, reads = _send_request(anon_client.app, "/api/disks", chunks=_endless())  # a pezzi
    assert status == 401 and json.loads(body)["detail"]["code"] == "auth_setup_required"
    assert reads == 1


def test_an_endless_chunked_body_stops_at_the_limit(client):
    for path, limit in (("/api/auth/login", LOGIN_BODY_BYTES), ("/api/auth/setup", LOGIN_BODY_BYTES),
                        ("/api/disks", MAX_BODY_BYTES)):
        status, body, reads = _send_request(client.app, path, chunks=_endless(), headers=[_bearer(client)])
        assert status == 413, path
        assert json.loads(body)["detail"] == {"code": "request_too_large", "params": {"limit": limit}}
        assert reads <= limit // CHUNK + 2


def test_with_a_valid_token_or_write_key_a_large_body_reaches_the_route(client):
    payload = _empty_objects(MAX_BODY_BYTES - 1)
    status, _body, _ = _send_request(client.app, "/api/disks", chunks=[payload],
                                    headers=[_length(payload), _bearer(client)])
    assert status == 422  # letto e validato: un elenco non è un disco
    write_key = client.post("/api/api-keys", json={"name": "rw", "level": "write"}).json()["key"]
    status, _, _ = _send_request(client.app, "/api/disks", chunks=[payload],
                                 headers=[_length(payload), (b"x-api-key", write_key.encode())])
    assert status == 422


def test_a_wrong_token_or_a_read_only_key_gets_the_route_error_before_the_body(client):
    payload = b'{"path": "/mnt"}'
    wrong = (b"authorization", b"Bearer not-a-token")
    status, body, reads = _send_request(client.app, "/api/disks", chunks=[payload], headers=[_length(payload), wrong])
    assert (status, json.loads(body)["detail"]["code"], reads) == (401, "auth_required", 0)
    read_key = client.post("/api/api-keys", json={"name": "ro", "level": "read"}).json()["key"]
    status, body, reads = _send_request(client.app, "/api/disks", chunks=[payload],
                                        headers=[_length(payload), (b"x-api-key", read_key.encode())])
    assert (status, json.loads(body)["detail"]["code"], reads) == (403, "api_key_read_only", 0)


def test_a_normal_login_still_goes_through(anon_client):
    payload = json.dumps({"username": "admin", "password": "x" * (LOGIN_BODY_BYTES // 2)}).encode()
    status, _, _ = _send_request(anon_client.app, "/api/auth/login", chunks=[payload], headers=[_length(payload)])
    assert status == 401  # letto e controllato: nessun account ancora


def test_a_validation_error_does_not_echo_the_input(anon_client):
    response = anon_client.post("/api/auth/login", json=[{"secret": "x" * 1000}])
    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert set(error) == {"type", "loc", "msg"}
    assert "x" * 100 not in response.text
    wrong = anon_client.post("/api/auth/login", json={"username": 1})
    assert wrong.status_code == 422
    assert all(set(error) == {"type", "loc", "msg"} for error in wrong.json()["detail"])
    assert {tuple(error["loc"]) for error in wrong.json()["detail"]} == {("body", "username"), ("body", "password")}
