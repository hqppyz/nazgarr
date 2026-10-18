"""Gli indirizzi dei servizi nelle richieste (nazgarr/api/types.py)."""

import socket

import pytest
from pydantic import TypeAdapter, ValidationError

from nazgarr.api.types import HttpUrlStr, host_changed
from nazgarr.core import net_guard


def _resolver(table):
    def resolve(host, *args, **kwargs):
        if host not in table:
            raise socket.gaierror(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], 0))]
    return resolve


def test_the_validator_never_waits_for_the_dns(monkeypatch):
    # I validatori girano sul loop di FastAPI: una risoluzione lenta fermava
    # ogni richiesta del processo (audit 2026-10-18).
    def no_dns(*args, **kwargs):
        raise AssertionError("DNS dal validatore")

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", no_dns)
    adapter = TypeAdapter(HttpUrlStr)
    assert adapter.validate_python(" https://tracker.example/ ") == "https://tracker.example/"
    monkeypatch.undo()
    with pytest.raises(ValidationError):  # un IP scritto per esteso si controlla subito
        adapter.validate_python("http://169.254.169.254/latest")
    with pytest.raises(ValidationError):
        adapter.validate_python("http://:8080")


def test_a_name_that_points_at_the_cloud_metadata_is_refused_by_the_endpoint(client, monkeypatch):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _resolver({"meta.example": "169.254.169.254",
                                                                    "ok.example": "192.168.1.10"}))
    tracker = {"label": "t", "adapter_type": "unit3d", "base_url": "https://meta.example", "api_token": "x"}
    refused = client.post("/api/trackers", json=tracker)
    assert refused.status_code == 422
    assert refused.json()["detail"] == {"code": "instance_url_forbidden", "params": {"url": "meta.example"}}
    announce = {**tracker, "base_url": "https://ok.example",
                "announce_url": "https://meta.example/announce/0123456789abcdef0123"}
    refused = client.post("/api/trackers", json=announce)
    assert refused.status_code == 422 and "0123456789abcdef" not in refused.text  # mai la passkey
    created = client.post("/api/trackers", json={**tracker, "base_url": "https://ok.example"})
    assert created.status_code == 201
    tracker_id = created.json()["id"]
    assert client.patch(f"/api/trackers/{tracker_id}", json={"base_url": "https://meta.example",
                                                             "api_token": "y"}).status_code == 422

    qbit = {"label": "q", "adapter_type": "qbittorrent", "base_url": "http://meta.example:8080"}
    assert client.post("/api/torrent-clients", json=qbit).status_code == 422
    qbit_id = client.post("/api/torrent-clients", json={**qbit, "base_url": "http://ok.example:8080"}).json()["id"]
    assert client.patch(f"/api/torrent-clients/{qbit_id}", json={"base_url": "http://meta.example:8080"}
                        ).status_code == 422
    assert client.post("/api/torrent-clients/qui-instances", json={"base_url": "http://meta.example",
                                                                   "api_token": "t"}).status_code == 422

    radarr = {"label": "r", "base_url": "http://meta.example:7878", "api_key": "k"}
    assert client.post("/api/radarr-instances", json=radarr).status_code == 422
    assert client.post("/api/radarr-instances/test", json=radarr).status_code == 422
    radarr_id = client.post("/api/radarr-instances", json={**radarr, "base_url": "http://ok.example:7878"}
                            ).json()["id"]
    assert client.patch(f"/api/radarr-instances/{radarr_id}", json={"base_url": "http://meta.example:7878",
                                                                    "api_key": "k2"}).status_code == 422


def test_going_from_https_to_http_counts_as_a_new_host():
    assert host_changed("https://t.example", "http://t.example")
    assert not host_changed("http://t.example", "https://t.example")  # verso https: niente di nuovo in chiaro
    assert not host_changed("https://t.example", "https://T.example/")
    assert host_changed("https://t.example", "https://other.example")
    assert not host_changed("https://t.example", None)


def test_a_downgrade_to_http_needs_the_secrets_again(client):
    # Prima https -> http sullo stesso host teneva token e chiave RSS, e la
    # ricerca dopo li mandava in chiaro (anche da una API key di scrittura).
    created = client.post("/api/trackers", json={"label": "t", "adapter_type": "unit3d",
                                                 "base_url": "https://t.example", "api_token": "tok",
                                                 "rss_key": "rss"}).json()
    downgraded = client.patch(f"/api/trackers/{created['id']}", json={"base_url": "http://t.example"})
    assert downgraded.status_code == 400
    assert downgraded.json()["detail"]["code"] == "secret_required_for_new_host"
    ok = client.patch(f"/api/trackers/{created['id']}", json={"base_url": "http://t.example", "api_token": "tok"})
    assert ok.status_code == 200 and ok.json()["has_rss_key"] is False  # non gliela si manda in chiaro
