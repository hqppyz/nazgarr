import pytest

from nazgarr.torrents.client_paths import ClientPathError, Mapping, to_client, to_disk_relative


def test_a_client_on_a_subfolder_both_ways(tmp_path):
    root = tmp_path / "data"
    (root / "qbittorrent" / "movies").mkdir(parents=True)
    (root / "media").mkdir()
    mapping = Mapping(str(root), "/download", "qbittorrent")

    assert to_client(mapping, str(root / "qbittorrent" / "movies")) == "/download/movies"
    assert to_client(mapping, str(root / "qbittorrent")) == "/download"
    assert to_disk_relative(mapping, "/download/movies/a.mkv") == "qbittorrent/movies/a.mkv"
    assert to_disk_relative(mapping, "/elsewhere/a.mkv") is None
    assert to_disk_relative(mapping, "/downloads2/a.mkv") is None  # non un prefisso a metà nome
    # Fuori dalla sottocartella il client non vede niente: errore, mai un percorso sbagliato.
    with pytest.raises(ClientPathError) as exc:
        to_client(mapping, str(root / "media"))
    assert exc.value.code == "client_cannot_see_path"


def test_the_disk_root_and_no_mapping_as_before(tmp_path):
    root = tmp_path / "disk1"
    (root / "torrents").mkdir(parents=True)
    whole = Mapping(str(root), "/downloads")
    assert to_client(whole, str(root / "torrents")) == "/downloads/torrents"
    assert to_disk_relative(whole, "/downloads/torrents/a.mkv") == "torrents/a.mkv"
    # Un percorso fuori dal disco: errore anche senza sottocartella, mai inventato.
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ClientPathError):
        to_client(whole, str(other))
    same = Mapping(str(root))
    assert to_client(same, str(root / "torrents")) == str(root / "torrents")
    assert to_disk_relative(same, str(root / "torrents" / "a.mkv")) == "torrents/a.mkv"


def test_the_save_path_handed_to_the_client(db_session, tmp_path):
    from nazgarr.core.models import Disk, DiskTorrentClient, TorrentClient
    from nazgarr.reseed.executor import client_visible_path

    root = tmp_path / "data"
    (root / "qbittorrent" / "reseed").mkdir(parents=True)
    (root / "uploads").mkdir()
    disk = Disk(label="main", root_path=str(root))
    tc = TorrentClient(label="qbit", adapter_type="qbittorrent", base_url="http://qbit")
    db_session.add_all([disk, tc])
    db_session.commit()
    db_session.add(DiskTorrentClient(disk_id=disk.id, torrent_client_id=tc.id, torrent_client_root_path="/download",
                                     local_rel_path="qbittorrent"))
    db_session.commit()

    assert client_visible_path(db_session, disk, tc.id, str(root / "qbittorrent" / "reseed")) == "/download/reseed"
    with pytest.raises(ClientPathError):
        client_visible_path(db_session, disk, tc.id, str(root / "uploads"))  # il client non la vede
    assert client_visible_path(db_session, disk, None, str(root / "uploads")) == str(root / "uploads")


def test_the_client_root_is_cleaned_or_refused(client):
    root = client.scan_root / "data"
    (root / "torrents").mkdir(parents=True)
    disk_id = client.post("/api/disks", json={"label": "main", "root_path": str(root)}).json()["id"]
    tc = client.post("/api/torrent-clients", json={"label": "q", "adapter_type": "qbittorrent",
                                                   "base_url": "http://q"}).json()["id"]

    saved = client.post(f"/api/torrent-clients/{tc}/disks/{disk_id}",
                        json={"torrent_client_root_path": "  /downloads/ ", "local_rel_path": "torrents"})
    assert saved.status_code == 204
    assert client.get("/api/torrent-clients").json()[0]["disks"][0]["torrent_client_root_path"] == "/downloads"
    for value in ("downloads", "D:\\torrents", "./x"):
        refused = client.post(f"/api/torrent-clients/{tc}/disks/{disk_id}", json={"torrent_client_root_path": value})
        assert refused.status_code == 400 and refused.json()["detail"]["code"] == "client_root_not_absolute", value


def test_a_coded_error_on_a_reseed_is_saved_as_readable_text():
    from nazgarr.reseed.executor import _error_text

    text = _error_text(ClientPathError("client_cannot_see_path", path="/data/x", folder="/data/torrents",
                                       client_root="/downloads"))
    assert "/data/x" in text and "/downloads" in text and "client_cannot_see_path" not in text
    assert _error_text(RuntimeError("boom")) == "boom"
