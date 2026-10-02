"""Cache delle viste della libreria (nazgarr/response_cache.py): ETag sulla
versione dei dati, 304 se il browser ha già quella versione, ricalcolo solo
quando cambia; gzip sulle risposte grandi."""

from nazgarr import library


def test_same_version_answers_304_without_recomputing(client, monkeypatch):
    calls = []
    real = library.media_file_states
    monkeypatch.setattr(library, "media_file_states", lambda *a, **k: calls.append(1) or real(*a, **k))

    first = client.get("/api/media-files")
    etag = first.headers["etag"]
    again = client.get("/api/media-files", headers={"If-None-Match": etag})
    other_client = client.get("/api/media-files")  # senza ETag: stessa versione, dalla cache in memoria

    assert first.status_code == 200 and again.status_code == 304 and other_client.status_code == 200
    assert other_client.json() == first.json()
    assert len(calls) == 1
    assert first.headers["cache-control"] == "private, no-cache"


def test_a_change_that_affects_the_views_changes_the_version(client):
    etag = client.get("/api/media-files").headers["etag"]
    client.put("/api/settings/exclusion_patterns", json={"value": "*.nfo"})

    after = client.get("/api/media-files", headers={"If-None-Match": etag})

    assert after.status_code == 200
    assert after.headers["etag"] != etag


def test_large_responses_are_gzipped(client):
    response = client.get("/api/health", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200  # piccola: sotto la soglia, nessun obbligo di gzip
    big = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert big.headers.get("content-encoding") == "gzip"
