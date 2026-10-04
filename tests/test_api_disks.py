def test_available_mounts_lists_unassigned_subfolders(client):
    (client.scan_root / "disk1").mkdir()
    (client.scan_root / "disk2").mkdir()

    response = client.get("/api/disks/available-mounts")

    assert response.status_code == 200
    body = response.json()
    assert body["scan_root"] == str(client.scan_root)
    mounts = body["mounts"]
    assert str(client.scan_root / "disk1") in mounts
    assert str(client.scan_root / "disk2") in mounts


def test_create_disk_then_disappears_from_available_mounts(client):
    (client.scan_root / "disk1").mkdir()

    create = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(client.scan_root / "disk1")})
    assert create.status_code == 201
    disk_id = create.json()["id"]

    mounts = client.get("/api/disks/available-mounts").json()["mounts"]
    assert str(client.scan_root / "disk1") not in mounts

    listed = client.get("/api/disks").json()
    assert any(d["id"] == disk_id for d in listed)


def test_create_disk_rejects_path_outside_scan_root(client, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    response = client.post("/api/disks", json={"label": "Bad", "root_path": str(outside)})

    assert response.status_code == 400


def test_browse_rejects_path_traversal(client):
    (client.scan_root / "disk1").mkdir()
    create = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(client.scan_root / "disk1")})
    disk_id = create.json()["id"]

    response = client.get(f"/api/disks/{disk_id}/browse", params={"path": "../../etc"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "path_outside_scope"


def test_get_disk_not_found_returns_coded_error(client):
    response = client.get("/api/disks/999999/browse")

    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "disk_not_found", "params": {"id": 999999}}


def test_update_disk_label(client):
    (client.scan_root / "disk1").mkdir()
    created = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(client.scan_root / "disk1")}).json()

    response = client.patch(f"/api/disks/{created['id']}", json={"label": "Renamed"})

    assert response.status_code == 200
    assert response.json()["label"] == "Renamed"


def test_update_disk_media_rel_path_and_new_torrent_rel_path(client):
    (client.scan_root / "disk1" / "media").mkdir(parents=True)
    created = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(client.scan_root / "disk1")}).json()
    assert created["media_rel_path"] is None
    assert created["new_torrent_rel_path"] is None

    response = client.patch(
        f"/api/disks/{created['id']}",
        json={"media_rel_path": "media", "new_torrent_rel_path": "torrents/new"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["media_rel_path"] == "media"
    assert body["new_torrent_rel_path"] == "torrents/new"


def test_browse_lists_file_sizes(client):
    disk_dir = client.scan_root / "disk1"
    (disk_dir / "Show").mkdir(parents=True)
    (disk_dir / "movie.mkv").write_bytes(b"x" * 42)
    disk_id = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(disk_dir)}).json()["id"]

    entries = client.get(f"/api/disks/{disk_id}/browse").json()["entries"]

    assert entries == [
        {"name": "movie.mkv", "is_dir": False, "size_bytes": 42},
        {"name": "Show", "is_dir": True, "size_bytes": None},
    ]


def test_the_watched_folder_is_validated(client):
    root = client.scan_root / "disk1"
    for folder in ("media/movies", "torrents/movies", "releases/new"):
        (root / folder).mkdir(parents=True)
    created = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(root)}).json()
    url = f"/api/disks/{created['id']}"
    client.patch(url, json={"media_rel_path": "media", "torrents_rel_path": "torrents"})

    # Mai il disco intero, la cartella media o dei torrent, né una che le
    # contiene; una sottocartella dedicata sì (es. torrents/movies qui sotto).
    for bad in (".", "media", "torrents", "releases/.."):
        response = client.patch(url, json={"watch_rel_path": bad})
        assert response.status_code == 400, bad
        assert response.json()["detail"]["code"] == "watch_folder_overlaps"
    assert client.patch(url, json={"watch_rel_path": "missing"}).json()["detail"]["code"] == "watch_folder_not_found"
    assert client.patch(url, json={"watch_rel_path": "../outside"}).json()["detail"]["code"] == "path_outside_scope"

    assert client.patch(url, json={"watch_rel_path": "torrents/movies"}).status_code == 200
    ok = client.patch(url, json={"watch_rel_path": "releases/new/"})
    assert ok.status_code == 200 and ok.json()["watch_rel_path"] == "releases/new"
    assert client.patch(url, json={"watch_rel_path": ""}).json()["watch_rel_path"] is None



def test_a_folder_where_a_client_downloads_is_never_watched(client):
    from datetime import UTC, datetime

    from nazgarr.core.models import ClientTorrent, ClientTorrentFile, SeedFile, TorrentClient
    from nazgarr.reseed import pipeline

    root = client.scan_root / "disk1"
    (root / "torrents" / "movies").mkdir(parents=True)
    created = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(root)}).json()
    session = client.app.state.session_factory()
    try:
        run = pipeline.start_run(session, "manual")
        tc = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q")
        seed = SeedFile(disk_id=created["id"], relative_path="torrents/movies/A.mkv", size_bytes=1, st_dev=1, inode=1,
                        last_scan_id=run.id, last_seen_at=datetime.now(UTC))
        session.add_all([tc, seed])
        session.commit()
        torrent = ClientTorrent(torrent_client_id=tc.id, info_hash="h", name="A", save_path="/x", state="uploading",
                                last_polled_at=datetime.now(UTC))
        session.add(torrent)
        session.commit()
        session.add(ClientTorrentFile(client_torrent_id=torrent.id, path_in_torrent="A.mkv", size_bytes=1,
                                      seed_file_id=seed.id, last_scan_id=run.id))
        session.commit()
    finally:
        session.close()

    response = client.patch(f"/api/disks/{created['id']}", json={"watch_rel_path": "torrents/movies"})

    assert response.json()["detail"]["code"] == "watch_folder_used_by_client"
