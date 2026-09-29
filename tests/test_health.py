"""Fase 0 — smoke test: il container si avvia, legge config.yaml, applica
lo schema DB e risponde su /api/health (definition of done, docs/ROADMAP.md)."""


def test_health(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert (client.scan_root.parent / "data" / "nazgarr.db").exists()
