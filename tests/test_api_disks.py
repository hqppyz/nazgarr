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
    (client.scan_root / "disk1").mkdir()
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

    # Mai il disco intero, né dentro o sopra la cartella media o dei torrent:
    # ogni import o download partirebbe come una release.
    for bad in (".", "media", "media/movies", "torrents/movies"):
        response = client.patch(url, json={"watch_rel_path": bad})
        assert response.status_code == 400, bad
        assert response.json()["detail"]["code"] == "watch_folder_overlaps"
    assert client.patch(url, json={"watch_rel_path": "missing"}).json()["detail"]["code"] == "watch_folder_not_found"
    assert client.patch(url, json={"watch_rel_path": "../outside"}).json()["detail"]["code"] == "path_outside_scope"

    ok = client.patch(url, json={"watch_rel_path": "releases/new/"})
    assert ok.status_code == 200 and ok.json()["watch_rel_path"] == "releases/new"
    assert client.patch(url, json={"watch_rel_path": ""}).json()["watch_rel_path"] is None
