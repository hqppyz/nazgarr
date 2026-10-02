import os

from nazgarr import file_changes, pipeline, scanner, settings_repo, torrent_indexer
from nazgarr.adapters.torrent_client.base import ClientTorrentFileInfo, ClientTorrentInfo, TorrentClientAdapter
from nazgarr.api.dashboard import get_changes
from nazgarr.models import Disk, FileChange, TorrentClient


class FakeAdapter(TorrentClientAdapter):
    def __init__(self, torrents):
        self._torrents = torrents

    def add_torrent(self, *args, **kwargs):
        raise NotImplementedError

    def get_torrent_status(self, *args, **kwargs):
        raise NotImplementedError

    def list_torrents(self):
        return self._torrents


def _scan(db_session, disk, tc, root, torrents):
    run = pipeline.start_run(db_session, run_type="manual")
    scanner.scan_disk(db_session, disk, run)
    torrent_indexer.index_torrent_client(db_session, tc, FakeAdapter([
        ClientTorrentInfo(info_hash=f"h-{name}", name=name, save_path=str(root / "torrents"), state=state,
                          files=[ClientTorrentFileInfo(path_in_torrent=name, size_bytes=1)])
        for name, state in torrents
    ]), run)
    count = file_changes.record_changes(db_session, run)
    run.finished_at = run.started_at
    db_session.commit()
    return count


def test_changes_between_two_scans(db_session, tmp_path):
    root = tmp_path / "disk"
    (root / "media").mkdir(parents=True)
    (root / "torrents").mkdir()
    disk = Disk(label="d", root_path=str(root), media_rel_path="media", torrents_rel_path="torrents")
    tc = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q")
    db_session.add_all([disk, tc])
    db_session.commit()
    for name in ("Kept.mkv", "Gone.mkv", "Linked.mkv", "Paused.mkv"):
        (root / "media" / name).write_bytes(name.encode())
    for name in ("Linked.mkv", "Paused.mkv"):
        os.link(root / "media" / name, root / "torrents" / name)

    # Prima scansione: solo la fotografia, nessun cambiamento.
    assert _scan(db_session, disk, tc, root, [("Paused.mkv", "uploading")]) == 0

    (root / "media" / "Gone.mkv").unlink()
    (root / "media" / "New.mkv").write_bytes(b"new")
    (root / "media" / "sample.mkv").write_bytes(b"s")
    settings_repo.set_setting(db_session, "exclusion_patterns", "*sample*")
    _scan(db_session, disk, tc, root, [("Linked.mkv", "uploading"), ("Paused.mkv", "stoppedUP")])

    kinds = {(c.side, os.path.basename(c.relative_path)): c.change for c in db_session.query(FileChange).all()}
    assert kinds == {
        ("media", "New.mkv"): "added",
        ("media", "Gone.mkv"): "removed",
        ("media", "Linked.mkv"): "state",  # orfano -> seeding
        ("torrent", "Linked.mkv"): "state",
        ("media", "Paused.mkv"): "stopped",
        ("torrent", "Paused.mkv"): "stopped",
    }  # sample.mkv escluso: nessun cambiamento

    body = get_changes(session=db_session)
    assert body.counts == {"new_media": 1, "removed_media": 1, "now_seeding": 2, "stopped": 2}
    assert body.baseline_only is False and body.since is not None
