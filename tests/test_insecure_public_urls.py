"""http:// verso un host pubblico per tracker, client torrent e Radarr/Sonarr
(decisione dell'utente, 2026-10-18): si salva lo stesso, con un avviso
calcolato (insecure_public_url); nessun avviso per la LAN, il loopback o
Tailscale, né per https."""

import socket

import pytest

from nazgarr.api import types

ADDRESSES = {
    "tracker.public.example": "93.184.216.34", "seedbox.public.example": "93.184.216.35",
    "radarr.public.example": "93.184.216.36", "qbit.lan": "192.168.1.20", "box.ts.net": "100.101.102.103",
}


@pytest.fixture(autouse=True)
def _dns(monkeypatch):
    real = socket.getaddrinfo  # quello senza rete di conftest

    def resolve(host, port, *args, **kwargs):
        if host in ADDRESSES:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ADDRESSES[host], 0))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    types.forget_public_hosts()
    yield
    types.forget_public_hosts()


def test_the_rule():
    assert types.insecure_public_url("http://tracker.public.example") is True
    assert types.insecure_public_url("http://93.184.216.34:8080") is True
    for url in ("https://tracker.public.example", "http://qbit.lan:8080", "http://box.ts.net:7878",
                "http://192.168.1.10:8080", "http://127.0.0.1:9091", "http://localhost:8080", "http://[::1]:80",
                "http://10.0.0.5", None, ""):
        assert types.insecure_public_url(url) is False, url
    # Un nome che non si risolve: nel dubbio l'avviso, come per le istanze.
    assert types.insecure_public_url("http://nowhere.invalid") is True


def test_a_name_that_does_not_resolve_is_public_only_for_a_short_while(monkeypatch):
    """Il nome di un container in LAN che per un momento manca dal DNS (fermo,
    o il DNS di Docker che singhiozza): l'avviso, ma tenuto 30 s, non 10
    minuti; un nome che si risolve resta tenuto 10 minuti."""
    clock = [1000.0]
    monkeypatch.setattr(types.time, "monotonic", lambda: clock[0])
    assert types.insecure_public_url("http://qbittorrent:8080") is True  # non si risolve

    monkeypatch.setitem(ADDRESSES, "qbittorrent", "172.17.0.5")  # il container è ripartito
    clock[0] += types.UNRESOLVED_HOST_TTL_SECONDS - 1
    assert types.insecure_public_url("http://qbittorrent:8080") is True  # ancora il verdetto tenuto
    clock[0] += 2
    assert types.insecure_public_url("http://qbittorrent:8080") is False

    # Risolto, il verdetto resta tenuto il tempo lungo.
    monkeypatch.setitem(ADDRESSES, "qbittorrent", "93.184.216.40")
    clock[0] += types.UNRESOLVED_HOST_TTL_SECONDS + 1
    assert types.insecure_public_url("http://qbittorrent:8080") is False


def test_a_tracker_over_plain_http_to_a_public_host_is_saved_with_the_warning(client):
    created = client.post("/api/trackers", json={
        "label": "t", "adapter_type": "unit3d", "base_url": "http://tracker.public.example",
        "api_token": "tok", "upload_profile": "none",
    })
    assert created.status_code == 201 and created.json()["insecure_public_url"] is True
    tracker_id = created.json()["id"]
    assert client.get("/api/trackers").json()[0]["insecure_public_url"] is True

    fixed = client.patch(f"/api/trackers/{tracker_id}", json={"base_url": "https://tracker.public.example"})
    assert fixed.status_code == 200 and fixed.json()["insecure_public_url"] is False


def test_a_client_on_the_lan_has_no_warning_and_a_seedbox_has_one(client):
    lan = client.post("/api/torrent-clients", json={
        "label": "lan", "adapter_type": "qbittorrent", "base_url": "http://qbit.lan:8080"})
    seedbox = client.post("/api/torrent-clients", json={
        "label": "box", "adapter_type": "qbittorrent", "base_url": "http://seedbox.public.example:8080",
        "username": "u", "password": "p"})
    tailscale = client.post("/api/torrent-clients", json={
        "label": "ts", "adapter_type": "qbittorrent", "base_url": "http://box.ts.net:8080"})

    assert lan.json()["insecure_public_url"] is False
    assert seedbox.json()["insecure_public_url"] is True
    assert tailscale.json()["insecure_public_url"] is False
    listed = {c["label"]: c["insecure_public_url"] for c in client.get("/api/torrent-clients").json()}
    assert listed == {"lan": False, "box": True, "ts": False}


@pytest.mark.parametrize("kind", ["radarr", "sonarr"])
def test_an_arr_instance_over_plain_http_to_a_public_host_has_the_warning(client, kind):
    created = client.post(f"/api/{kind}-instances", json={
        "label": "x", "base_url": "http://radarr.public.example:7878", "api_key": "k"})
    local = client.post(f"/api/{kind}-instances", json={"label": "y", "base_url": "http://qbit.lan:7878",
                                                         "api_key": "k"})

    assert created.status_code == 201 and created.json()["insecure_public_url"] is True
    assert local.json()["insecure_public_url"] is False
