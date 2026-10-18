"""Il login è obbligatorio (decisione dell'utente, 2026-10-01), e in
nazgarr/main.py lo si aggiunge a ogni include_router a mano: un argomento
dimenticato su un router nuovo aprirebbe i suoi endpoint a chiunque, e
nessun altro test se ne accorgerebbe (audit 2026-10-18). Qui ogni operazione
dello schema OpenAPI si chiama senza credenziali."""

import re

# Le sole aperte: senza, nessuno potrebbe creare l'account o entrare, e
# l'HEALTHCHECK del container non ha credenziali.
PUBLIC = {
    ("GET", "/api/auth/status"),
    ("POST", "/api/auth/setup"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/health"),
}
# Solo con il login, mai con una API key.
LOGIN_ONLY = ("/api/api-keys", "/api/instances", "/api/remote/", "/api/auth/change-password",
              "/api/auth/logout-everywhere")


def _operations(app):
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/"):
            continue  # il catch-all del frontend: index.html, nessun dato
        for method in operations:
            yield method.upper(), path, re.sub(r"\{[^}]+\}", "1", path)


def _setup(client):
    body = {"username": "admin", "password": "supersecret1", "setup_code": client.app.state.setup_code}
    response = client.post("/api/auth/setup", json=body)
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_every_api_route_needs_the_login(anon_client):
    _setup(anon_client)
    open_routes = []
    checked = 0
    for method, path, url in _operations(anon_client.app):
        if (method, path) in PUBLIC:
            continue
        checked += 1
        if anon_client.request(method, url).status_code != 401:
            open_routes.append(f"{method} {path}")
    assert open_routes == []
    assert checked > 100  # davvero tutte, non uno schema vuoto


def test_the_public_ones_are_still_reachable(anon_client):
    assert anon_client.get("/api/auth/status").status_code == 200
    assert anon_client.get("/api/health").status_code == 200


def test_an_api_key_cannot_use_the_login_only_routes(anon_client):
    login = _setup(anon_client)
    created = anon_client.post("/api/api-keys", json={"name": "script", "level": "write"}, headers=login)
    key = {"X-Api-Key": created.json()["key"]}
    allowed = []
    for method, path, url in _operations(anon_client.app):
        if path.startswith(LOGIN_ONLY) and anon_client.request(method, url, headers=key).status_code != 403:
            allowed.append(f"{method} {path}")
    assert allowed == []
