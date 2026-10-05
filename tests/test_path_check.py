"""Verifica dei percorsi di un client (nazgarr/torrents/path_check.py): i tre
scenari della retrospettiva del 2026-10-05."""

from nazgarr.adapters.torrent_client.base import ClientTorrentFileInfo, ClientTorrentInfo
from nazgarr.core.models import Disk, DiskFolder, DiskTorrentClient, TorrentClient
from nazgarr.torrents import path_check
from nazgarr.torrents.path_check import Sample


def _file(path, size=1000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _disk(session, root, label="main", seeding=("torrents",)):
    disk = Disk(label=label, root_path=str(root))
    session.add(disk)
    session.flush()
    for folder in seeding:
        (root / folder).mkdir(parents=True, exist_ok=True)
        session.add(DiskFolder(disk_id=disk.id, kind="seeding", relative_path=folder))
    session.commit()
    return disk


def _client(session):
    tc = TorrentClient(label="qbit", adapter_type="qbittorrent", base_url="http://qbit")
    session.add(tc)
    session.commit()
    return tc


def test_same_paths_need_nothing(db_session, tmp_path):
    """(i) TRaSH: client e Nazgarr vedono /data allo stesso modo."""
    root = tmp_path / "data"
    _file(root / "torrents" / "movies" / "Dune" / "dune.mkv")
    disk = _disk(db_session, root)
    tc = _client(db_session)

    result = path_check.check(db_session, tc, [Sample(f"{disk.root_path}/torrents/movies/Dune/dune.mkv", 1000)], "live")

    assert (result.verdict, result.counts["ok"], result.suggestions) == ("ok", 1, [])


def test_a_client_on_a_subfolder_gets_the_right_mapping_suggested(db_session, tmp_path):
    """(ii) Il client monta solo torrents/ come /downloads: senza corrispondenza
    niente torna, e la proposta è "torrents = /downloads". Con quella, tutto ok."""
    root = tmp_path / "data"
    _file(root / "torrents" / "movies" / "Dune" / "dune.mkv")
    _file(root / "torrents" / "tv" / "Show.S01" / "e01.mkv", 2000)
    disk = _disk(db_session, root)
    tc = _client(db_session)
    samples = [Sample("/downloads/movies/Dune/dune.mkv", 1000), Sample("/downloads/tv/Show.S01/e01.mkv", 2000)]

    result = path_check.check(db_session, tc, samples, "live")

    assert (result.verdict, result.counts["unmapped"]) == ("none", 2)
    [suggestion] = result.suggestions
    assert (suggestion.disk_id, suggestion.local_rel_path, suggestion.client_root_path, suggestion.matches) == (
        disk.id, "torrents", "/downloads", 2)

    db_session.add(DiskTorrentClient(disk_id=disk.id, torrent_client_id=tc.id, local_rel_path="torrents",
                                     torrent_client_root_path="/downloads"))
    db_session.commit()
    fixed = path_check.check(db_session, tc, samples, "live")
    assert (fixed.verdict, fixed.suggestions) == ("ok", [])


def test_the_whole_disk_mapped_by_mistake_is_caught(db_session, tmp_path):
    """L'errore più probabile: "tutto il disco" = /downloads quando il client
    vede solo torrents/. Il file si cerca in /data/movies/..., che non c'è."""
    root = tmp_path / "data"
    _file(root / "torrents" / "movies" / "dune.mkv")
    disk = _disk(db_session, root)
    tc = _client(db_session)
    db_session.add(DiskTorrentClient(disk_id=disk.id, torrent_client_id=tc.id, torrent_client_root_path="/downloads"))
    db_session.commit()

    result = path_check.check(db_session, tc, [Sample("/downloads/movies/dune.mkv", 1000)], "live")

    assert (result.verdict, result.counts["missing"]) == ("none", 1)
    assert result.examples[0].local_path == f"{root}/movies/dune.mkv"
    assert [(s.local_rel_path, s.client_root_path) for s in result.suggestions] == [("torrents", "/downloads")]


def test_unraid_disks_seen_through_the_user_share(db_session, tmp_path):
    """(iii) Nazgarr monta /mnt/disk1 e /mnt/disk2, il client vede la share
    /mnt/user/data: una proposta per ogni disco. Un disco dimenticato (solo
    disk1 associato) lascia fuori i file del disco 2, e la verifica lo dice."""
    disk1_root, disk2_root = tmp_path / "disk1", tmp_path / "disk2"
    _file(disk1_root / "data" / "torrents" / "a.mkv")
    _file(disk2_root / "data" / "torrents" / "b.mkv", 3000)
    disk1 = _disk(db_session, disk1_root, "disk1", seeding=("data/torrents",))
    disk2 = _disk(db_session, disk2_root, "disk2", seeding=("data/torrents",))
    tc = _client(db_session)
    samples = [Sample("/mnt/user/data/torrents/a.mkv", 1000), Sample("/mnt/user/data/torrents/b.mkv", 3000)]

    result = path_check.check(db_session, tc, samples, "live")
    assert {(s.disk_id, s.local_rel_path, s.client_root_path) for s in result.suggestions} == {
        (disk1.id, "data/torrents", "/mnt/user/data/torrents"), (disk2.id, "data/torrents", "/mnt/user/data/torrents")}

    db_session.add(DiskTorrentClient(disk_id=disk1.id, torrent_client_id=tc.id, local_rel_path="data/torrents",
                                     torrent_client_root_path="/mnt/user/data/torrents"))
    db_session.commit()
    partial = path_check.check(db_session, tc, samples, "live")
    assert (partial.verdict, partial.counts["ok"], partial.counts["missing"]) == ("partial", 1, 1)
    assert [s.disk_id for s in partial.suggestions] == [disk2.id]


def test_a_file_outside_the_seeding_folders_is_reported_not_remapped(db_session, tmp_path):
    root = tmp_path / "data"
    _file(root / "cross-seed" / "x.mkv")
    disk = _disk(db_session, root)
    tc = _client(db_session)

    result = path_check.check(db_session, tc, [Sample(f"{disk.root_path}/cross-seed/x.mkv", 1000)], "live")

    assert (result.verdict, result.counts["outside_seeding"], result.suggestions) == ("none", 1, [])


def test_a_different_size_is_not_the_same_file(db_session, tmp_path):
    root = tmp_path / "data"
    _file(root / "torrents" / "x.mkv", 10)
    disk = _disk(db_session, root)
    tc = _client(db_session)

    result = path_check.check(db_session, tc, [Sample(f"{disk.root_path}/torrents/x.mkv", 99)], "live")

    assert result.counts["missing"] == 1 and result.suggestions == []


def test_the_api_reads_the_index_or_asks_the_client(client, monkeypatch):
    root = client.scan_root / "data"
    (root / "torrents").mkdir(parents=True)
    (root / "torrents" / "x.mkv").write_bytes(b"x" * 5)
    disk_id = client.post("/api/disks", json={"label": "main", "root_path": str(root)}).json()["id"]
    added = client.post(f"/api/disks/{disk_id}/folders", json={"kind": "seeding", "relative_path": "torrents"})
    assert added.status_code == 201, added.text
    tc = client.post("/api/torrent-clients", json={"label": "q", "adapter_type": "qbittorrent",
                                                   "base_url": "http://q"}).json()["id"]

    class Live:
        def list_torrents(self):
            return [ClientTorrentInfo("h1", "x", "/downloads", "uploading",
                                      files=[ClientTorrentFileInfo("x.mkv", 5)])]

        def close(self):
            pass

    monkeypatch.setattr("nazgarr.integrations.adapter_factory.build_torrent_client_adapter", lambda tc: Live())
    body = client.post(f"/api/torrent-clients/{tc}/path-check").json()
    assert (body["status"], body["source"], body["verdict"], body["unmapped"]) == ("ok", "live", "none", 1)
    assert body["suggestions"] == [{"disk_id": disk_id, "disk_label": "main", "local_rel_path": "torrents",
                                    "client_root_path": "/downloads", "matches": 1}]
    assert client.post("/api/torrent-clients/999/path-check").status_code == 404
