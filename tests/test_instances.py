import pytest
from fastapi.testclient import TestClient

from nazgarr import instances


@pytest.mark.parametrize("remote, local, expected", [
    ("0.7.3", "0.7.7", "ok"),            # stessa minor: le patch non contano
    ("0.6.64", "0.7.7", "warn"),         # l'altra è più vecchia di una minor
    ("0.8.0", "0.7.7", "block_newer"),   # l'altra è più nuova: questa UI non la conosce
    ("1.0.0", "0.7.7", "block_major"),
    ("0.7.7", "1.2.0", "block_major"),
    ("0.7.0-dev", "0.7.4", "ok"),
    (None, "0.7.7", "unknown"),
])
def test_version_compatibility(remote, local, expected):
    assert instances.compatibility(remote, local) == expected


def test_a_public_address_needs_https(monkeypatch):
    def resolve(host, *args):
        ip = {"nas.lan": "192.168.1.10", "box.ts.net": "100.101.102.103", "vps.example": "93.184.216.34",
              "meta": "169.254.169.254"}[host]
        return [(None, None, None, None, (ip, 0))]

    monkeypatch.setattr(instances.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(instances.net_guard.socket, "getaddrinfo", resolve)
    assert instances.normalize_url("http://nas.lan:8080/") == "http://nas.lan:8080"
    assert instances.normalize_url("http://box.ts.net:8080") == "http://box.ts.net:8080"  # Tailscale
    assert instances.normalize_url("https://vps.example") == "https://vps.example"
    for url, code in (("http://vps.example", "instance_needs_https"), ("http://meta", "instance_url_forbidden"),
                      ("ftp://nas.lan", "instance_url_invalid")):
        with pytest.raises(instances.InstanceError) as exc:
            instances.normalize_url(url)
        assert exc.value.code == code


def test_the_proxy_paths():
    assert instances.proxied_path("api/disks") == "/api/disks"
    for path in ("api/auth/me", "api/api-keys", "api/remote/1/api/disks", "api/instances", "static/x", "api/../x"):
        with pytest.raises(instances.InstanceError):
            instances.proxied_path(path)


class _NoLifespan(TestClient):
    """Un client sull'app già avviata dal fixture: senza ripartire (e fermare) l'app."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


@pytest.fixture
def remote(client, monkeypatch):
    """L'"altra" istanza è questa stessa app, raggiunta con una sua API key."""
    from nazgarr.main import app

    instances._health.clear()
    monkeypatch.setattr(instances, "CLIENT_FACTORY", lambda base_url, key: _NoLifespan(
        app, base_url=base_url, headers={"X-Api-Key": key} if key else {}))

    def add(level="write", label="Seedbox"):
        key = client.post("/api/api-keys", json={"name": f"hub-{level}", "level": level}).json()["key"]
        response = client.post("/api/instances", json={"label": label, "base_url": "https://box.example",
                                                       "api_key": key})
        assert response.status_code == 201, response.text
        return response.json()

    return add


def test_an_instance_is_tested_when_added(client, remote):
    created = remote()
    assert created["status"]["status"] == "ok" and created["status"]["level"] == "write"
    assert created["status"]["compatibility"] == "ok"
    listed = client.get("/api/instances", params={"probe": True}).json()
    assert [i["label"] for i in listed["instances"]] == ["Seedbox"] and "api_key" not in str(listed)


def test_the_proxy_reaches_the_other_instance(client, remote):
    instance = remote()
    base = f"/api/remote/{instance['id']}"
    assert client.get(f"{base}/api/disks").json() == []
    assert client.get(f"{base}/api/system/whoami").json()["kind"] == "api_key"
    # Mai login e chiavi dell'altra istanza.
    assert client.get(f"{base}/api/auth/me").status_code == 403
    assert client.get(f"{base}/api/api-keys").status_code == 403


def test_a_read_only_key_only_looks(client, remote):
    instance = remote(level="read")
    assert instance["status"]["level"] == "read"
    response = client.post(f"/api/remote/{instance['id']}/api/runs")
    assert response.status_code == 403 and response.json()["detail"]["code"] == "api_key_read_only"


def test_an_incompatible_instance_is_refused(client, remote, monkeypatch):
    instance = remote()
    instances._health.clear()
    monkeypatch.setattr(instances, "probe", lambda url, key: {
        "status": "ok", "error": None, "version": "0.9.0", "level": "write", "compatibility": "block_newer"})
    response = client.get(f"/api/remote/{instance['id']}/api/disks")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "instance_incompatible"


def test_an_api_key_of_this_instance_cannot_use_the_others(client, remote):
    remote()
    key = client.post("/api/api-keys", json={"name": "script", "level": "write"}).json()["key"]
    from nazgarr.main import app

    other = _NoLifespan(app, headers={"X-Api-Key": key})
    assert other.get("/api/instances").status_code == 403
    assert other.get("/api/remote/1/api/disks").status_code == 403


def test_an_older_instance_without_whoami_is_still_connected(monkeypatch):
    # Una 0.7.x non ha /api/system/whoami: la sua pagina risponde con HTML.
    import httpx

    def handler(request):
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "version": "0.7.5"})
        return httpx.Response(200, text="<html>spa</html>", headers={"content-type": "text/html"})

    monkeypatch.setattr(instances, "CLIENT_FACTORY", lambda base_url, key: httpx.Client(
        base_url=base_url, transport=httpx.MockTransport(handler)))

    result = instances.probe("http://old.lan", "nzg_x")

    assert (result["status"], result["version"], result["level"]) == ("ok", "0.7.5", None)
