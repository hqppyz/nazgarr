from datetime import UTC, datetime

from nazgarr import pipeline, torrent_indexer
from nazgarr.adapters.torrent_client.base import ClientTorrentFileInfo, ClientTorrentInfo, TorrentClientAdapter
from nazgarr.models import ClientTorrentFile, Disk, DiskTorrentClient, SeedFile, TorrentClient


class FakeAdapter(TorrentClientAdapter):
    def __init__(self, torrents):
        self._torrents = torrents

    def add_torrent(self, *args, **kwargs):
        raise NotImplementedError

    def get_torrent_status(self, *args, **kwargs):
        raise NotImplementedError

    def list_torrents(self):
        return self._torrents


def _make_disk_and_client(db_session, root_path, torrent_client_root_path=None):
    disk = Disk(label="disk1", root_path=root_path, torrents_rel_path="torrents")
    db_session.add(disk)
    db_session.commit()

    tc = TorrentClient(label="qbt", adapter_type="qbittorrent", base_url="http://qbt")
    db_session.add(tc)
    db_session.commit()
    db_session.add(DiskTorrentClient(
        disk_id=disk.id, torrent_client_id=tc.id, torrent_client_root_path=torrent_client_root_path,
    ))
    db_session.commit()

    return disk, tc


def _make_seed_file(db_session, disk, relative_path, run):
    sf = SeedFile(
        disk_id=disk.id, relative_path=relative_path, size_bytes=123,
        st_dev=1, inode=1, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(sf)
    db_session.commit()
    return sf


def test_resolves_seed_file_by_path_same_root(db_session):
    disk, tc = _make_disk_and_client(db_session, root_path="/mnt/disk1")
    run = pipeline.start_run(db_session, run_type="manual")
    seed_file = _make_seed_file(db_session, disk, "torrents/Movie.2024.mkv", run)

    adapter = FakeAdapter([
        ClientTorrentInfo(
            info_hash="h1", name="Movie.2024.mkv", save_path="/mnt/disk1/torrents", state="uploading",
            files=[ClientTorrentFileInfo(path_in_torrent="Movie.2024.mkv", size_bytes=123)],
        )
    ])

    counts = torrent_indexer.index_torrent_client(db_session, tc, adapter, run)

    assert counts == {"torrents_indexed": 1, "files_indexed": 1, "files_linked": 1, "torrents_removed": 0}
    ctf = db_session.query(ClientTorrentFile).one()
    assert ctf.seed_file_id == seed_file.id


def test_resolves_seed_file_when_client_sees_different_root(db_session):
    # Il client vede il contenuto sotto /downloads, noi sotto /mnt/disk1 —
    # stesso disco fisico, mount diversi (docs/SPEC.md sezione 4).
    disk, tc = _make_disk_and_client(db_session, root_path="/mnt/disk1", torrent_client_root_path="/downloads")
    run = pipeline.start_run(db_session, run_type="manual")
    seed_file = _make_seed_file(db_session, disk, "torrents/Movie.2024.mkv", run)

    adapter = FakeAdapter([
        ClientTorrentInfo(
            info_hash="h1", name="Movie.2024.mkv", save_path="/downloads/torrents", state="uploading",
            files=[ClientTorrentFileInfo(path_in_torrent="Movie.2024.mkv", size_bytes=123)],
        )
    ])

    torrent_indexer.index_torrent_client(db_session, tc, adapter, run)

    ctf = db_session.query(ClientTorrentFile).one()
    assert ctf.seed_file_id == seed_file.id


def test_two_clients_on_same_disk_can_have_different_root_paths(db_session):
    # Il gap che ha motivato lo spostamento del campo dal disco alla
    # coppia (disk, torrent_client): due client sullo stesso disco fisico,
    # ciascuno con un mount interno diverso.
    disk = Disk(label="disk1", root_path="/mnt/disk1", torrents_rel_path="torrents")
    db_session.add(disk)
    db_session.commit()
    tc_a = TorrentClient(label="qbt-a", adapter_type="qbittorrent", base_url="http://qbt-a")
    tc_b = TorrentClient(label="qbt-b", adapter_type="qbittorrent", base_url="http://qbt-b")
    db_session.add_all([tc_a, tc_b])
    db_session.commit()
    db_session.add_all([
        DiskTorrentClient(disk_id=disk.id, torrent_client_id=tc_a.id, torrent_client_root_path="/downloads-a"),
        DiskTorrentClient(disk_id=disk.id, torrent_client_id=tc_b.id, torrent_client_root_path="/downloads-b"),
    ])
    db_session.commit()
    run = pipeline.start_run(db_session, run_type="manual")
    seed_file = _make_seed_file(db_session, disk, "torrents/Movie.2024.mkv", run)

    adapter_a = FakeAdapter([
        ClientTorrentInfo(
            info_hash="ha", name="Movie.2024.mkv", save_path="/downloads-a/torrents", state="uploading",
            files=[ClientTorrentFileInfo(path_in_torrent="Movie.2024.mkv", size_bytes=123)],
        )
    ])
    adapter_b = FakeAdapter([
        ClientTorrentInfo(
            info_hash="hb", name="Movie.2024.mkv", save_path="/downloads-b/torrents", state="uploading",
            files=[ClientTorrentFileInfo(path_in_torrent="Movie.2024.mkv", size_bytes=123)],
        )
    ])

    torrent_indexer.index_torrent_client(db_session, tc_a, adapter_a, run)
    torrent_indexer.index_torrent_client(db_session, tc_b, adapter_b, run)

    files = db_session.query(ClientTorrentFile).all()
    assert len(files) == 2
    assert all(f.seed_file_id == seed_file.id for f in files)


def test_unresolved_file_has_null_seed_file_id(db_session):
    disk, tc = _make_disk_and_client(db_session, root_path="/mnt/disk1")
    run = pipeline.start_run(db_session, run_type="manual")
    # nessun seed_file corrispondente creato

    adapter = FakeAdapter([
        ClientTorrentInfo(
            info_hash="h1", name="Ghost.mkv", save_path="/mnt/disk1/torrents", state="uploading",
            files=[ClientTorrentFileInfo(path_in_torrent="Ghost.mkv", size_bytes=1)],
        )
    ])

    torrent_indexer.index_torrent_client(db_session, tc, adapter, run)

    ctf = db_session.query(ClientTorrentFile).one()
    assert ctf.seed_file_id is None


def test_repolling_does_not_duplicate_rows(db_session):
    disk, tc = _make_disk_and_client(db_session, root_path="/mnt/disk1")
    run = pipeline.start_run(db_session, run_type="manual")
    _make_seed_file(db_session, disk, "torrents/Movie.2024.mkv", run)

    adapter = FakeAdapter([
        ClientTorrentInfo(
            info_hash="h1", name="Movie.2024.mkv", save_path="/mnt/disk1/torrents", state="uploading",
            files=[ClientTorrentFileInfo(path_in_torrent="Movie.2024.mkv", size_bytes=123)],
        )
    ])

    torrent_indexer.index_torrent_client(db_session, tc, adapter, run)
    torrent_indexer.index_torrent_client(db_session, tc, adapter, run)

    assert db_session.query(ClientTorrentFile).count() == 1


def test_client_with_no_disks_still_indexes_torrents_without_linking(db_session):
    tc = TorrentClient(label="qbt", adapter_type="qbittorrent", base_url="http://qbt")
    db_session.add(tc)
    db_session.commit()
    run = pipeline.start_run(db_session, run_type="manual")

    adapter = FakeAdapter([
        ClientTorrentInfo(
            info_hash="h1", name="Movie.mkv", save_path="/anywhere", state="uploading",
            files=[ClientTorrentFileInfo(path_in_torrent="Movie.mkv", size_bytes=1)],
        )
    ])

    counts = torrent_indexer.index_torrent_client(db_session, tc, adapter, run)

    assert counts == {"torrents_indexed": 1, "files_indexed": 1, "files_linked": 0, "torrents_removed": 0}
    assert db_session.query(ClientTorrentFile).one().seed_file_id is None


def test_client_without_associations_is_matched_against_every_disk_by_path(db_session):
    """Caso comune (TRaSH Guides): client e Nazgarr vedono gli stessi
    percorsi, nessuna associazione disco-client da configurare."""
    disk = Disk(label="FUSE", root_path="/data", torrents_rel_path="torrents")
    tc = TorrentClient(label="qui", adapter_type="qui", base_url="http://qui")
    db_session.add_all([disk, tc])
    db_session.commit()
    run = pipeline.start_run(db_session, run_type="manual")
    seed_file = _make_seed_file(db_session, disk, "torrents/completed/tv/Show.S01E06.mkv", run)

    adapter = FakeAdapter([
        ClientTorrentInfo(
            info_hash="h1", name="Show.S01E06.mkv", save_path="/data/torrents/completed/tv", state="uploading",
            files=[ClientTorrentFileInfo(path_in_torrent="Show.S01E06.mkv", size_bytes=123)],
        )
    ])

    counts = torrent_indexer.index_torrent_client(db_session, tc, adapter, run)

    assert counts["files_linked"] == 1
    assert db_session.query(ClientTorrentFile).one().seed_file_id == seed_file.id


def test_a_torrent_removed_from_the_client_leaves_the_index(db_session):
    from nazgarr.models import ClientTorrent

    disk, tc = _make_disk_and_client(db_session, root_path="/mnt/disk1")
    run = pipeline.start_run(db_session, run_type="manual")
    kept = _make_seed_file(db_session, disk, "torrents/Kept.mkv", run)
    _make_seed_file(db_session, disk, "torrents/Removed.mkv", run)
    both = [
        ClientTorrentInfo(info_hash=h, name=f"{n}.mkv", save_path="/mnt/disk1/torrents", state="stoppedUP",
                          files=[ClientTorrentFileInfo(path_in_torrent=f"{n}.mkv", size_bytes=123)])
        for h, n in (("h1", "Kept"), ("h2", "Removed"))
    ]
    torrent_indexer.index_torrent_client(db_session, tc, FakeAdapter(both), run)

    later = pipeline.start_run(db_session, run_type="manual")
    counts = torrent_indexer.index_torrent_client(db_session, tc, FakeAdapter(both[:1]), later)

    assert counts["torrents_removed"] == 1
    assert [ct.info_hash for ct in db_session.query(ClientTorrent).all()] == ["h1"]
    assert [f.seed_file_id for f in db_session.query(ClientTorrentFile).all()] == [kept.id]


def test_the_single_torrent_refresh_never_removes_the_others(db_session):
    from nazgarr.models import ClientTorrent

    disk, tc = _make_disk_and_client(db_session, root_path="/mnt/disk1")
    run = pipeline.start_run(db_session, run_type="manual")
    torrents = [
        ClientTorrentInfo(info_hash=h, name=h, save_path="/mnt/disk1/torrents", state="uploading", files=[])
        for h in ("h1", "h2")
    ]
    torrent_indexer.index_torrent_client(db_session, tc, FakeAdapter(torrents), run)

    torrent_indexer.store_client_torrents(db_session, tc, torrents[:1], run.id)

    assert db_session.query(ClientTorrent).count() == 2
