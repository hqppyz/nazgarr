"""Fase 0 — smoke test: il container si avvia, legge config.yaml, applica
lo schema DB e risponde su /api/health (definition of done, docs/ROADMAP.md)."""


def test_health(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert (client.scan_root.parent / "data" / "nazgarr.db").exists()


def test_only_who_is_logged_in_learns_the_exact_build(client):
    # A un visitatore anonimo versione e commit dicevano quale build attaccare
    # (audit 2026-10-18); all'HEALTHCHECK del container basta lo status.
    anonymous = client.get("/api/health", headers={"Authorization": ""})
    assert anonymous.status_code == 200 and anonymous.json() == {"status": "ok", "version": None, "commit": None}
    assert client.get("/api/health", headers={"Authorization": "Bearer garbage"}).json()["version"] is None
    assert client.get("/api/health", headers={"Authorization": "", "X-Api-Key": "nzg_wrong"}).json()["version"] is None

    key = client.post("/api/api-keys", json={"name": "probe", "level": "read"}).json()["key"]
    assert client.get("/api/health", headers={"Authorization": "", "X-Api-Key": key}).json()["version"]


def test_the_broken_swagger_pages_are_gone(client):
    # La CSP bloccava i loro script dal CDN: pagine vuote. Resta lo schema.
    for path in ("/docs", "/redoc"):
        response = client.get(path)
        assert "swagger-ui" not in response.text and "redoc.standalone" not in response.text
    assert client.get("/openapi.json").json()["paths"]
