def test_create_list_update_delete_torrent_client(client):
    create = client.post(
        "/api/torrent-clients",
        json={"label": "qbt", "adapter_type": "qbittorrent", "base_url": "http://qbt:8080", "username": "admin"},
    )
    assert create.status_code == 201
    tc_id = create.json()["id"]
    assert create.json()["enabled"] is True

    listed = client.get("/api/torrent-clients").json()
    assert any(tc["id"] == tc_id for tc in listed)

    update = client.patch(f"/api/torrent-clients/{tc_id}", json={"enabled": False})
    assert update.status_code == 200
    assert update.json()["enabled"] is False

    delete = client.delete(f"/api/torrent-clients/{tc_id}")
    assert delete.status_code == 204
    assert client.get("/api/torrent-clients").json() == []


def test_rejects_unsupported_adapter_type(client):
    response = client.post(
        "/api/torrent-clients",
        json={"label": "deluge", "adapter_type": "deluge", "base_url": "http://deluge:8112"},
    )
    assert response.status_code == 400


def test_connection_test_reports_success(client, monkeypatch):
    tc_id = client.post(
        "/api/torrent-clients", json={"label": "qbt", "adapter_type": "qbittorrent", "base_url": "http://qbt"}
    ).json()["id"]

    class FakeAdapter:
        def list_torrents(self):
            return [object(), object(), object()]

    monkeypatch.setattr("nazgarr.adapter_factory.build_torrent_client_adapter", lambda tc: FakeAdapter())

    response = client.post(f"/api/torrent-clients/{tc_id}/test")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "torrents_found": 3, "error": None}


def test_connection_test_reports_failure_against_unreachable_host(client):
    # Porta 1 su localhost: quasi certamente nessuno in ascolto, connection
    # refused immediato — nessuna chiamata di rete reale verso l'esterno.
    tc_id = client.post(
        "/api/torrent-clients",
        json={"label": "qbt", "adapter_type": "qbittorrent", "base_url": "http://127.0.0.1:1"},
    ).json()["id"]

    response = client.post(f"/api/torrent-clients/{tc_id}/test")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]


def test_associate_and_dissociate_disk(client):
    (client.scan_root / "disk1").mkdir()
    disk_create = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(client.scan_root / "disk1")})
    disk_id = disk_create.json()["id"]
    tc_id = client.post(
        "/api/torrent-clients", json={"label": "qbt", "adapter_type": "qbittorrent", "base_url": "http://qbt"}
    ).json()["id"]

    associate = client.post(f"/api/torrent-clients/{tc_id}/disks/{disk_id}")
    assert associate.status_code == 204
    disks = client.get("/api/torrent-clients").json()[0]["disks"]
    assert disks == [{"disk_id": disk_id, "torrent_client_root_path": None}]

    # idempotente: associare due volte non deve fallire né duplicare
    again = client.post(f"/api/torrent-clients/{tc_id}/disks/{disk_id}")
    assert again.status_code == 204
    disks = client.get("/api/torrent-clients").json()[0]["disks"]
    assert disks == [{"disk_id": disk_id, "torrent_client_root_path": None}]

    dissociate = client.delete(f"/api/torrent-clients/{tc_id}/disks/{disk_id}")
    assert dissociate.status_code == 204
    assert client.get("/api/torrent-clients").json()[0]["disks"] == []


def test_associate_disk_with_root_path_override(client):
    # Il motivo per cui l'override vive sulla coppia (disk, client) e non sul
    # disco: due client diversi sullo stesso disco possono vederlo montato
    # a path diversi nei rispettivi container.
    (client.scan_root / "disk1").mkdir()
    disk_id = client.post(
        "/api/disks", json={"label": "Disk 1", "root_path": str(client.scan_root / "disk1")}
    ).json()["id"]
    tc_a = client.post(
        "/api/torrent-clients", json={"label": "qbt-a", "adapter_type": "qbittorrent", "base_url": "http://a"}
    ).json()["id"]
    tc_b = client.post(
        "/api/torrent-clients", json={"label": "qbt-b", "adapter_type": "qbittorrent", "base_url": "http://b"}
    ).json()["id"]

    client.post(f"/api/torrent-clients/{tc_a}/disks/{disk_id}", json={"torrent_client_root_path": "/downloads-a"})
    client.post(f"/api/torrent-clients/{tc_b}/disks/{disk_id}", json={"torrent_client_root_path": "/downloads-b"})

    by_id = {tc["id"]: tc["disks"] for tc in client.get("/api/torrent-clients").json()}
    assert by_id[tc_a] == [{"disk_id": disk_id, "torrent_client_root_path": "/downloads-a"}]
    assert by_id[tc_b] == [{"disk_id": disk_id, "torrent_client_root_path": "/downloads-b"}]

    # re-associare aggiorna l'override invece di fallire
    client.post(f"/api/torrent-clients/{tc_a}/disks/{disk_id}", json={"torrent_client_root_path": "/downloads-a2"})
    updated = next(tc for tc in client.get("/api/torrent-clients").json() if tc["id"] == tc_a)
    assert updated["disks"] == [{"disk_id": disk_id, "torrent_client_root_path": "/downloads-a2"}]
