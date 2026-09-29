"""Fixture condivise dai test del flusso di upload v2."""

from app import upload_profiles
from app.models import Disk, TorrentClient, Tracker


class InlineExecutor:
    """Esegue subito quello che riceve: il worker nei test gira nel thread
    del test, senza attese né race."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

    def shutdown(self, wait=True, cancel_futures=False):
        pass


def make_tracker(session, label="t", *, with_profile=True, announce_url="https://tracker.example/announce", **extra):
    tracker = Tracker(
        label=label, adapter_type="unit3d", base_url=f"https://{label}.example", api_token="x",
        announce_url=announce_url, **extra,
    )
    session.add(tracker)
    session.commit()
    if with_profile:
        upload_profiles.create_upload_profile(session, tracker, None)
    return tracker


def make_client(session, label="qbit", enabled=True):
    client = TorrentClient(
        label=label, adapter_type="qbittorrent", base_url="http://qbit", username="u", password="p", enabled=enabled
    )
    session.add(client)
    session.commit()
    return client


def make_disk(session, root_path):
    disk = Disk(label="d", root_path=str(root_path))
    session.add(disk)
    session.commit()
    return disk


def write_video(path, size=20000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path
