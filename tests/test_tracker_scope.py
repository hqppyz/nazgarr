from datetime import UTC, datetime

import pytest

from app import health, library, pipeline, tracker_scope
from app.models import ClientTorrent, ClientTorrentFile, Disk, MediaFile, SeedFile, TorrentClient, Tracker


@pytest.fixture
def world(db_session):
    """Tre film: A in seed su ITT, B solo su un tracker pubblico, C su ITT ma
    da un client disattivato; più un file orfano senza torrent."""
    disk = Disk(label="d", root_path="/data", media_rel_path="media", torrents_rel_path="torrents")
    itt = Tracker(label="ITT", adapter_type="unit3d", base_url="https://itatorrents.xyz", api_token="x",
                  announce_url="https://itatorrents.xyz/announce/key")
    on = TorrentClient(label="qbit private", adapter_type="qbittorrent", base_url="http://q1")
    off = TorrentClient(label="qbit public", adapter_type="qbittorrent", base_url="http://q2", enabled=False)
    db_session.add_all([disk, itt, on, off])
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    now = datetime.now(UTC)

    def media(name, inode):
        mf = MediaFile(disk_id=disk.id, relative_path=f"media/{name}.mkv", size_bytes=100, st_dev=1, inode=inode,
                       last_scan_id=run.id, last_seen_at=now)
        db_session.add(mf)
        return mf

    def seed(name, inode):
        sf = SeedFile(disk_id=disk.id, relative_path=f"torrents/{name}.mkv", size_bytes=100, st_dev=1, inode=inode,
                      last_scan_id=run.id, last_seen_at=now)
        db_session.add(sf)
        return sf

    mfs = [media("A", 1), media("B", 2), media("C", 3)]
    sfs = [seed("A", 1), seed("B", 2), seed("C", 3), seed("orphan", 9)]
    db_session.commit()
    for mf, sf in zip(mfs, sfs, strict=False):
        sf.media_file_id = mf.id
    torrents = [
        (on, "https://itatorrents.xyz/announce/key", sfs[0]),
        (on, "udp://tracker.public.example:1337/announce", sfs[1]),
        (off, "https://itatorrents.xyz/announce/key", sfs[2]),
    ]
    for i, (client, url, sf) in enumerate(torrents):
        ct = ClientTorrent(torrent_client_id=client.id, info_hash=f"h{i}", name=f"t{i}", save_path="/t",
                           state="uploading", tracker_url=url, last_polled_at=now)
        db_session.add(ct)
        db_session.commit()
        db_session.add(ClientTorrentFile(client_torrent_id=ct.id, path_in_torrent=f"t{i}.mkv", size_bytes=100,
                                         seed_file_id=sf.id, last_scan_id=run.id))
    db_session.commit()
    pipeline.close_interrupted_runs(db_session)
    return {"itt": itt, "run": run}


def _states(rows):
    return {r["relative_path"].split("/")[-1]: r["state"] for r in rows}


def test_all_keeps_every_torrent_as_before(db_session, world):
    expected = {"A.mkv": "seeding", "B.mkv": "seeding", "C.mkv": "seeding"}
    assert _states(library.media_file_states(db_session)) == expected


def test_a_tracker_counts_only_its_torrents_on_enabled_clients(db_session, world):
    itt = str(world["itt"].id)

    assert _states(library.media_file_states(db_session, tracker=itt)) == {
        "A.mkv": "seeding", "B.mkv": "orphan_media", "C.mkv": "orphan_media",
    }
    # "configured": lo stesso, il pubblico non conta.
    assert _states(library.media_file_states(db_session, tracker="configured"))["B.mkv"] == "orphan_media"


def test_torrent_view_hides_other_trackers_but_keeps_orphans(db_session, world):
    rows = _states(library.seed_file_states(db_session, tracker=str(world["itt"].id)))
    # B è in seed solo sul pubblico e C solo su un client spento: per ITT non ci
    # sono; l'orfano sì, può diventare un upload per qualunque tracker.
    assert rows == {"A.mkv": "seeding", "C.mkv": "orphan_torrent", "orphan.mkv": "orphan_torrent"}


def test_health_follows_the_filter(db_session, world):
    assert health.compute_snapshot(db_session)["health_pct"] == 100.0
    assert health.compute_snapshot(db_session, tracker=str(world["itt"].id))["health_pct"] == 33.3


def test_unknown_filters_do_not_restrict_anything():
    assert tracker_scope.normalize("bogus") == "all"
    assert tracker_scope.normalize(None) == "all"
    assert tracker_scope.normalize("7") == "7"


def test_scans_save_the_history_of_every_filter(db_session, world):
    from app.models import TrackerHealthSnapshot

    run = pipeline.start_run(db_session, "manual")
    pipeline._save_tracker_snapshots(db_session, run)
    db_session.commit()

    scopes = {s.scope: s.health_snapshot for s in db_session.query(TrackerHealthSnapshot).filter_by(run_id=run.id)}
    assert scopes == {"configured": 33.3, str(world["itt"].id): 33.3}
