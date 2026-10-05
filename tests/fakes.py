"""Finti e fabbriche comuni a più file di test."""

from datetime import UTC, datetime

from nazgarr.adapters.torrent_client.base import TorrentClientAdapter
from nazgarr.core.models import MediaFile


class FakeAdapter(TorrentClientAdapter):
    """Un client torrent che elenca i torrent ricevuti e non fa altro: per
    indicizzazione, stati della libreria, cambiamenti, non importati."""

    def __init__(self, torrents):
        self._torrents = torrents

    def add_torrent(self, *args, **kwargs):
        raise NotImplementedError

    def get_torrent_status(self, *args, **kwargs):
        raise NotImplementedError

    def list_torrents(self):
        return self._torrents


def make_media_file(session, disk, relative_path, run, **values) -> MediaFile:
    """Un media_file visto dalla scansione `run` (dimensione e inode finti,
    sovrascrivibili con values)."""
    mf = MediaFile(
        disk_id=disk.id, relative_path=relative_path, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        **{"size_bytes": 1, "st_dev": 1, "inode": 1, **values},
    )
    session.add(mf)
    session.commit()
    return mf
